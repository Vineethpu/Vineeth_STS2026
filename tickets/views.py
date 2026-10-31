from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import filters, generics, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import Roles, get_role, visible_tickets
from .models import Category, SLAPolicy, Ticket, TicketAttachment, TicketComment, TicketHistory
from .serializers import (
    CategorySerializer, SLAPolicySerializer, TicketAttachmentSerializer,
    TicketCommentSerializer, TicketHistorySerializer, TicketSerializer,
)


def write_history(ticket, user, field, old, new):
    TicketHistory.objects.create(
        Ticket=ticket, ChangedBy=user, Field=field,
        OldValue=str(old) if old is not None else None,
        NewValue=str(new) if new is not None else None,
    )


class CategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [Roles("Admin")]
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class SLAPolicyViewSet(viewsets.ModelViewSet):
    permission_classes = [Roles("Admin")]
    queryset = SLAPolicy.objects.all()
    serializer_class = SLAPolicySerializer


class TicketViewSet(viewsets.ModelViewSet):
    permission_classes = [Roles("Customer", "Agent", "Admin")]
    serializer_class = TicketSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["Title", "Description"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = visible_tickets(self.request.user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(Status=status_filter)
        return queryset

    def create(self, request, *args, **kwargs):
        if get_role(request.user) != "Customer":
            raise PermissionDenied("Only customers can create tickets.")
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        ticket = serializer.save(Customer=self.request.user, Status="Open", AssignedAgent=None)
        policy = SLAPolicy.objects.filter(Priority=ticket.Priority).first()
        if policy:
            ticket.ResponseDueAt = ticket.CreatedAt + timedelta(hours=policy.ResponseHours)
            ticket.save(update_fields=["ResponseDueAt"])
        write_history(ticket, self.request.user, "Status", None, "Open")

    @transaction.atomic
    def perform_update(self, serializer):
        user = self.request.user
        old_status = serializer.instance.Status
        old_agent = serializer.instance.AssignedAgent
        ticket = serializer.save()
        now = timezone.now()

        if ticket.Status != old_status:
            if ticket.Status == "In Progress" and ticket.FirstResponseAt is None:
                ticket.FirstResponseAt = now
            elif ticket.Status == "Resolved":
                ticket.ResolvedAt = now
            elif ticket.Status == "Closed":
                ticket.ClosedAt = now
            elif ticket.Status == "Open":
                ticket.ClosedAt = None
                ticket.ResolvedAt = None
            ticket.save(update_fields=["FirstResponseAt", "ResolvedAt", "ClosedAt"])
            write_history(ticket, user, "Status", old_status, ticket.Status)

        if ticket.AssignedAgent_id != (old_agent.id if old_agent else None):
            write_history(
                ticket, user, "AssignedAgent",
                old_agent.username if old_agent else None,
                ticket.AssignedAgent.username if ticket.AssignedAgent else None,
            )


class BreachedTicketsView(generics.ListAPIView):
    permission_classes = [Roles("Agent", "Admin")]
    serializer_class = TicketSerializer

    def get_queryset(self):
        return visible_tickets(self.request.user).filter(
            FirstResponseAt__isnull=True,
            ResponseDueAt__lt=timezone.now(),
        )


class TicketCommentViewSet(viewsets.ModelViewSet):
    permission_classes = [Roles("Customer", "Agent", "Admin")]
    serializer_class = TicketCommentSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = TicketComment.objects.filter(
            Ticket__in=visible_tickets(self.request.user)
        ).select_related("Author", "Ticket")
        if get_role(self.request.user) == "Customer":
            queryset = queryset.filter(IsInternal=False)
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            queryset = queryset.filter(Ticket_id=ticket_id)
        return queryset

    def perform_create(self, serializer):
        role = get_role(self.request.user)
        internal = serializer.validated_data.get("IsInternal", False)
        comment = serializer.save(Author=self.request.user, IsInternal=internal)
        ticket = comment.Ticket
        if role in ("Agent", "Admin") and not internal and ticket.FirstResponseAt is None:
            ticket.FirstResponseAt = timezone.now()
            ticket.save(update_fields=["FirstResponseAt"])


class TicketHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [Roles("Agent", "Admin")]
    serializer_class = TicketHistorySerializer

    def get_queryset(self):
        queryset = TicketHistory.objects.filter(
            Ticket__in=visible_tickets(self.request.user)
        ).select_related("ChangedBy", "Ticket")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            queryset = queryset.filter(Ticket_id=ticket_id)
        return queryset


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    permission_classes = [Roles("Customer", "Agent", "Admin")]
    serializer_class = TicketAttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = TicketAttachment.objects.filter(
            Ticket__in=visible_tickets(self.request.user)
        ).select_related("UploadedBy", "Ticket")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            queryset = queryset.filter(Ticket_id=ticket_id)
        return queryset

    def perform_create(self, serializer):
        uploaded_file = serializer.validated_data["File"]
        serializer.save(
            UploadedBy=self.request.user,
            OriginalName=uploaded_file.name,
            FileSize=uploaded_file.size,
        )


class DashboardView(APIView):
    permission_classes = [Roles("Admin")]

    def get(self, request):
        statuses = ["Open", "In Progress", "Resolved", "Closed"]
        by_status = {
            item["Status"]: item["total"]
            for item in Ticket.objects.values("Status").annotate(total=Count("TicketId"))
        }
        for item in statuses:
            by_status.setdefault(item, 0)

        resolved = Ticket.objects.filter(
            AssignedAgent__isnull=False, ResolvedAt__isnull=False
        ).select_related("AssignedAgent")
        durations = {}
        for ticket in resolved:
            hours = (ticket.ResolvedAt - ticket.CreatedAt).total_seconds() / 3600
            durations.setdefault(ticket.AssignedAgent.username, []).append(hours)

        per_agent = [
            {
                "Agent": agent,
                "ResolvedTickets": len(values),
                "AvgResolutionHours": round(sum(values) / len(values), 2),
            }
            for agent, values in durations.items()
        ]

        per_category = [
            {"Category": row["CategoryName"], "Tickets": row["ticket_count"]}
            for row in Category.objects.annotate(ticket_count=Count("tickets")).values(
                "CategoryName", "ticket_count"
            )
        ]

        return Response({
            "TicketsByStatus": by_status,
            "AvgResolutionPerAgent": per_agent,
            "TicketsPerCategory": per_category,
        })
