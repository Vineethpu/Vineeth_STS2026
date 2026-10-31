from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Ticket


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        role = get_role(user)
        token["role"] = role
        token["username"] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        return {
            "role": get_role(self.user),
            "username": self.user.username,
            "access": data["access"],
            "refresh": data["refresh"],
        }


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


def get_role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser or user.groups.filter(name="Admin").exists():
        return "Admin"
    if user.groups.filter(name="Agent").exists():
        return "Agent"
    if user.groups.filter(name="Customer").exists():
        return "Customer"
    return None


def Roles(*roles):
    class RolePermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            return bool(request.user and request.user.is_authenticated and get_role(request.user) in roles)

    return RolePermission


def visible_tickets(user):
    queryset = Ticket.objects.select_related("Category", "Customer", "AssignedAgent")
    role = get_role(user)
    if role == "Admin":
        return queryset
    if role == "Agent":
        return queryset.filter(AssignedAgent=user)
    if role == "Customer":
        return queryset.filter(Customer=user)
    return queryset.none()
