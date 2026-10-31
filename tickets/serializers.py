from datetime import timedelta
from pathlib import Path

from django.utils import timezone
from rest_framework import serializers

from .auth import get_role, visible_tickets
from .models import (
    NEXT_STATUS, Category, SLAPolicy, Ticket, TicketAttachment,
    TicketComment, TicketHistory, MAX_ATTACHMENT_SIZE,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["CategoryId", "CategoryName"]


class SLAPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SLAPolicy
        fields = ["SLAPolicyId", "Priority", "ResponseHours"]

    def validate_ResponseHours(self, value):
        if value < 1:
            raise serializers.ValidationError("ResponseHours must be at least 1.")
        return value


class TicketSerializer(serializers.ModelSerializer):
    CategoryName = serializers.CharField(source="Category.CategoryName", read_only=True)
    CustomerName = serializers.CharField(source="Customer.username", read_only=True)
    AssignedAgentName = serializers.CharField(source="AssignedAgent.username", read_only=True, allow_null=True)
    IsBreached = serializers.BooleanField(source="is_breached", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "TicketId", "Title", "Description", "Category", "CategoryName",
            "Priority", "Status", "Customer", "CustomerName", "AssignedAgent",
            "AssignedAgentName", "CreatedAt", "ResponseDueAt", "FirstResponseAt",
            "ResolvedAt", "ClosedAt", "IsBreached",
        ]
        read_only_fields = [
            "Customer", "CreatedAt", "ResponseDueAt", "FirstResponseAt",
            "ResolvedAt", "ClosedAt",
        ]

    def validate_Priority(self, value):
        if not SLAPolicy.objects.filter(Priority=value).exists():
            raise serializers.ValidationError(
                f"No SLA policy is configured for {value} priority. Ask an admin to configure it first."
            )
        return value

    def validate_Status(self, value):
        ticket = self.instance
        if ticket is None:
            if value != "Open":
                raise serializers.ValidationError("A new ticket must start with Open status.")
            return value

        role = get_role(self.context["request"].user)
        old = ticket.Status

        if role == "Customer":
            if not (old == "Closed" and value == "Open"):
                raise serializers.ValidationError("Customers may only reopen a closed ticket.")
            if ticket.ClosedAt is None or timezone.now() - ticket.ClosedAt > timedelta(days=7):
                raise serializers.ValidationError("A closed ticket can only be reopened within 7 days.")
            return value

        if role not in ("Agent", "Admin"):
            raise serializers.ValidationError("You cannot change ticket status.")

        if NEXT_STATUS.get(old) != value:
            expected = NEXT_STATUS.get(old) or "no further status"
            raise serializers.ValidationError(f"Invalid transition. Next allowed status: {expected}.")
        return value

    def validate_AssignedAgent(self, value):
        request_user = self.context["request"].user
        if self.instance is None:
            if value is not None:
                raise serializers.ValidationError("Customers cannot assign an agent during ticket creation.")
            return None

        if get_role(request_user) != "Admin":
            raise serializers.ValidationError("Only admins can assign or reassign tickets.")
        if value is None or not value.groups.filter(name="Agent").exists():
            raise serializers.ValidationError("Select a user belonging to the Agent role.")
        if self.instance.Status == "Closed":
            raise serializers.ValidationError("A closed ticket cannot be assigned.")
        return value

    def validate(self, attrs):
        if self.instance is None:
            return attrs

        immutable = {"Title", "Description", "Category", "Priority"}
        supplied = immutable.intersection(self.initial_data.keys())
        if supplied:
            raise serializers.ValidationError({
                field: "This field cannot be changed after ticket creation."
                for field in supplied
            })

        if attrs.get("Status") == "In Progress":
            assigned = attrs.get("AssignedAgent", self.instance.AssignedAgent)
            if assigned is None:
                raise serializers.ValidationError({"Status": "Assign an agent before starting work."})

        allowed = {"Status", "AssignedAgent"}
        unknown = set(self.initial_data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError({
                field: "This field cannot be updated here." for field in unknown
            })
        return attrs


class TicketCommentSerializer(serializers.ModelSerializer):
    AuthorName = serializers.CharField(source="Author.username", read_only=True)

    class Meta:
        model = TicketComment
        fields = ["CommentId", "Ticket", "Author", "AuthorName", "Message", "IsInternal", "CreatedAt"]
        read_only_fields = ["Author", "CreatedAt"]

    def validate_Ticket(self, value):
        user = self.context["request"].user
        if not visible_tickets(user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("Ticket not found.")
        return value

    def validate(self, attrs):
        role = get_role(self.context["request"].user)
        if attrs.get("IsInternal", False) and role not in ("Agent", "Admin"):
            raise serializers.ValidationError({"IsInternal": "Only agents and admins can create internal notes."})
        return attrs


class TicketHistorySerializer(serializers.ModelSerializer):
    ChangedByName = serializers.CharField(source="ChangedBy.username", read_only=True)

    class Meta:
        model = TicketHistory
        fields = [
            "HistoryId", "Ticket", "Field", "OldValue", "NewValue",
            "ChangedBy", "ChangedByName", "ChangedAt",
        ]


class TicketAttachmentSerializer(serializers.ModelSerializer):
    UploadedByName = serializers.CharField(source="UploadedBy.username", read_only=True)

    class Meta:
        model = TicketAttachment
        fields = [
            "AttachmentId", "Ticket", "File", "OriginalName", "FileSize",
            "UploadedBy", "UploadedByName", "UploadedAt",
        ]
        read_only_fields = ["OriginalName", "FileSize", "UploadedBy", "UploadedAt"]

    def validate_Ticket(self, value):
        if not visible_tickets(self.context["request"].user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("Ticket not found.")
        return value

    def validate_File(self, value):
        allowed = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}
        extension = Path(value.name).suffix.lower()
        if extension not in allowed:
            raise serializers.ValidationError("Allowed file types: PDF, PNG, JPG, JPEG and TXT.")
        if value.size > MAX_ATTACHMENT_SIZE:
            raise serializers.ValidationError("File too large. Maximum size is 5 MB.")
        return value
