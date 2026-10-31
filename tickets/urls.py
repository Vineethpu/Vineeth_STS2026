from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .auth import LoginView
from .views import (
    BreachedTicketsView, CategoryViewSet, DashboardView, SLAPolicyViewSet,
    TicketAttachmentViewSet, TicketCommentViewSet, TicketHistoryViewSet, TicketViewSet,
)

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("comments", TicketCommentViewSet, basename="comment")
router.register("history", TicketHistoryViewSet, basename="history")
router.register("attachments", TicketAttachmentViewSet, basename="attachment")
router.register("categories", CategoryViewSet, basename="category")
router.register("sla-policies", SLAPolicyViewSet, basename="sla-policy")

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("tickets/breached/", BreachedTicketsView.as_view(), name="breached-tickets"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("", include(router.urls)),
]
