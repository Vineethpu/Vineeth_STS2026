from django.contrib import admin
from .models import Category, SLAPolicy, Ticket, TicketAttachment, TicketComment, TicketHistory

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("TicketId", "Title", "Status", "Priority", "Customer", "AssignedAgent", "CreatedAt")
    list_filter = ("Status", "Priority", "Category")
    search_fields = ("Title", "Description", "Customer__username")
    readonly_fields = ("CreatedAt", "ResponseDueAt", "FirstResponseAt", "ResolvedAt", "ClosedAt")

admin.site.register(Category)
admin.site.register(SLAPolicy)
admin.site.register(TicketComment)
admin.site.register(TicketHistory)
admin.site.register(TicketAttachment)
