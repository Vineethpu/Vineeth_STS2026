from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone

PRIORITY_CHOICES = [
    ("Low", "Low"), ("Medium", "Medium"), ("High", "High"), ("Critical", "Critical")
]
STATUS_CHOICES = [
    ("Open", "Open"), ("In Progress", "In Progress"),
    ("Resolved", "Resolved"), ("Closed", "Closed")
]
NEXT_STATUS = {
    "Open": "In Progress",
    "In Progress": "Resolved",
    "Resolved": "Closed",
    "Closed": None,
}
MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "txt"]


def validate_attachment_size(file_obj):
    if file_obj.size > MAX_ATTACHMENT_SIZE:
        raise ValidationError("File too large. Maximum size is 5 MB.")


def validate_attachment_content_type(file_obj):
    content_type = getattr(file_obj, "content_type", "")
    allowed = {
        "application/pdf", "image/png", "image/jpeg", "text/plain",
        "application/octet-stream",
    }
    if content_type and content_type not in allowed:
        raise ValidationError("Unsupported file content type.")


class Category(models.Model):
    CategoryId = models.AutoField(primary_key=True)
    CategoryName = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["CategoryName"]
        indexes = [models.Index(fields=["CategoryName"], name="category_name_idx")]

    def __str__(self):
        return self.CategoryName


class SLAPolicy(models.Model):
    SLAPolicyId = models.AutoField(primary_key=True)
    Priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, unique=True)
    ResponseHours = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(ResponseHours__gte=1), name="sla_response_hours_positive")
        ]

    def __str__(self):
        return f"{self.Priority} - {self.ResponseHours} hours"


class Ticket(models.Model):
    TicketId = models.AutoField(primary_key=True)
    Title = models.CharField(max_length=150)
    Description = models.TextField()
    Category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="tickets")
    Priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="Medium")
    Status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="Open")
    Customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    AssignedAgent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_tickets"
    )
    CreatedAt = models.DateTimeField(auto_now_add=True)
    ResponseDueAt = models.DateTimeField(null=True, blank=True)
    FirstResponseAt = models.DateTimeField(null=True, blank=True)
    ResolvedAt = models.DateTimeField(null=True, blank=True)
    ClosedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-CreatedAt"]
        indexes = [
            models.Index(fields=["Status"], name="ticket_status_idx"),
            models.Index(fields=["Priority"], name="ticket_priority_idx"),
            models.Index(fields=["Customer", "CreatedAt"], name="ticket_customer_date_idx"),
            models.Index(fields=["AssignedAgent", "Status"], name="ticket_agent_status_idx"),
            models.Index(fields=["ResponseDueAt", "FirstResponseAt"], name="ticket_sla_due_idx"),
            models.Index(fields=["Category", "Status"], name="ticket_category_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(Title__gt=""), name="ticket_title_not_empty"),
        ]

    @property
    def is_breached(self):
        return (
            self.FirstResponseAt is None
            and self.ResponseDueAt is not None
            and timezone.now() > self.ResponseDueAt
        )

    def __str__(self):
        return f"#{self.TicketId} {self.Title} ({self.Status})"


class TicketComment(models.Model):
    CommentId = models.AutoField(primary_key=True)
    Ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    Author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    Message = models.TextField()
    IsInternal = models.BooleanField(default=False)
    CreatedAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["CreatedAt"]
        indexes = [
            models.Index(fields=["Ticket", "CreatedAt"], name="comment_ticket_date_idx"),
            models.Index(fields=["Ticket", "IsInternal"], name="comment_ticket_internal_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=~models.Q(Message=""), name="comment_message_not_empty")
        ]

    def __str__(self):
        return f"Comment {self.CommentId} on ticket {self.Ticket_id}"


class TicketHistory(models.Model):
    HistoryId = models.AutoField(primary_key=True)
    Ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    ChangedBy = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    Field = models.CharField(max_length=20)
    OldValue = models.CharField(max_length=100, null=True, blank=True)
    NewValue = models.CharField(max_length=100, null=True, blank=True)
    ChangedAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ChangedAt"]
        indexes = [
            models.Index(fields=["Ticket", "ChangedAt"], name="history_ticket_date_idx"),
            models.Index(fields=["Field", "ChangedAt"], name="history_field_date_idx"),
        ]

    def __str__(self):
        return f"{self.Field}: {self.OldValue} -> {self.NewValue}"


class TicketAttachment(models.Model):
    AttachmentId = models.AutoField(primary_key=True)
    Ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    UploadedBy = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    File = models.FileField(
        upload_to="ticket_attachments/",
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_ATTACHMENT_EXTENSIONS),
            validate_attachment_size,
            validate_attachment_content_type,
        ],
    )
    OriginalName = models.CharField(max_length=255)
    FileSize = models.PositiveIntegerField()
    UploadedAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-UploadedAt"]
        indexes = [models.Index(fields=["Ticket", "UploadedAt"], name="attachment_ticket_date_idx")]

    def __str__(self):
        return self.OriginalName
