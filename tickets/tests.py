from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, SLAPolicy, Ticket, TicketComment, TicketHistory


class SupportTicketAPITests(APITestCase):
    def setUp(self):
        self.customer_group, _ = Group.objects.get_or_create(name="Customer")
        self.agent_group, _ = Group.objects.get_or_create(name="Agent")
        self.admin_group, _ = Group.objects.get_or_create(name="Admin")

        self.customer = User.objects.create_user("customer1", password="Pass12345!")
        self.customer.groups.add(self.customer_group)
        self.other_customer = User.objects.create_user("customer2", password="Pass12345!")
        self.other_customer.groups.add(self.customer_group)
        self.agent = User.objects.create_user("agent1", password="Pass12345!")
        self.agent.groups.add(self.agent_group)
        self.admin = User.objects.create_user("admin1", password="Pass12345!")
        self.admin.groups.add(self.admin_group)

        self.category = Category.objects.create(CategoryName="Technical")
        SLAPolicy.objects.create(Priority="Low", ResponseHours=24)
        SLAPolicy.objects.create(Priority="Medium", ResponseHours=8)
        SLAPolicy.objects.create(Priority="High", ResponseHours=4)
        SLAPolicy.objects.create(Priority="Critical", ResponseHours=1)

    def create_ticket(self, customer=None, **kwargs):
        return Ticket.objects.create(
            Title=kwargs.get("Title", "Cannot login"),
            Description=kwargs.get("Description", "Login fails"),
            Category=self.category,
            Priority=kwargs.get("Priority", "Medium"),
            Customer=customer or self.customer,
            AssignedAgent=kwargs.get("AssignedAgent"),
            Status=kwargs.get("Status", "Open"),
            ResponseDueAt=kwargs.get("ResponseDueAt"),
            ClosedAt=kwargs.get("ClosedAt"),
        )

    def test_customer_can_create_ticket(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post("/api/tickets/", {
            "Title": "Printer issue", "Description": "Printer is offline",
            "Category": self.category.pk, "Priority": "High",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ticket = Ticket.objects.get(pk=response.data["TicketId"])
        self.assertEqual(ticket.Customer, self.customer)
        self.assertEqual(ticket.Status, "Open")
        self.assertIsNotNone(ticket.ResponseDueAt)

    def test_customer_sees_only_own_tickets(self):
        self.create_ticket()
        self.create_ticket(customer=self.other_customer, Title="Other ticket")
        self.client.force_authenticate(self.customer)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_agent_sees_only_assigned_tickets(self):
        self.create_ticket(AssignedAgent=self.agent)
        self.create_ticket(Title="Unassigned")
        self.client.force_authenticate(self.agent)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_only_admin_can_assign_agent(self):
        ticket = self.create_ticket()
        self.client.force_authenticate(self.customer)
        denied = self.client.patch(f"/api/tickets/{ticket.pk}/", {"AssignedAgent": self.agent.pk})
        self.assertEqual(denied.status_code, 400)
        self.client.force_authenticate(self.admin)
        allowed = self.client.patch(f"/api/tickets/{ticket.pk}/", {"AssignedAgent": self.agent.pk})
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(ticket.history.filter(Field="AssignedAgent").exists())

    def test_invalid_status_jump_is_rejected(self):
        ticket = self.create_ticket(AssignedAgent=self.agent)
        self.client.force_authenticate(self.agent)
        response = self.client.patch(f"/api/tickets/{ticket.pk}/", {"Status": "Resolved"})
        self.assertEqual(response.status_code, 400)

    def test_valid_status_transition_is_recorded(self):
        ticket = self.create_ticket(AssignedAgent=self.agent)
        self.client.force_authenticate(self.agent)
        response = self.client.patch(f"/api/tickets/{ticket.pk}/", {"Status": "In Progress"})
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.Status, "In Progress")
        self.assertTrue(ticket.history.filter(Field="Status", NewValue="In Progress").exists())

    def test_customer_can_reopen_closed_ticket_within_seven_days(self):
        ticket = self.create_ticket(Status="Closed", ClosedAt=timezone.now() - timedelta(days=2))
        self.client.force_authenticate(self.customer)
        response = self.client.patch(f"/api/tickets/{ticket.pk}/", {"Status": "Open"})
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_reopen_after_seven_days(self):
        ticket = self.create_ticket(Status="Closed", ClosedAt=timezone.now() - timedelta(days=8))
        self.client.force_authenticate(self.customer)
        response = self.client.patch(f"/api/tickets/{ticket.pk}/", {"Status": "Open"})
        self.assertEqual(response.status_code, 400)

    def test_customer_cannot_see_internal_notes(self):
        ticket = self.create_ticket()
        TicketComment.objects.create(Ticket=ticket, Author=self.agent, Message="Internal", IsInternal=True)
        TicketComment.objects.create(Ticket=ticket, Author=self.agent, Message="Public", IsInternal=False)
        self.client.force_authenticate(self.customer)
        response = self.client.get(f"/api/comments/?ticket={ticket.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertFalse(response.data["results"][0]["IsInternal"])

    def test_customer_cannot_create_internal_note(self):
        ticket = self.create_ticket()
        self.client.force_authenticate(self.customer)
        response = self.client.post("/api/comments/", {
            "Ticket": ticket.pk, "Message": "Private", "IsInternal": True,
        })
        self.assertEqual(response.status_code, 400)

    def test_breached_endpoint_returns_overdue_unanswered_tickets(self):
        ticket = self.create_ticket(
            AssignedAgent=self.agent,
            ResponseDueAt=timezone.now() - timedelta(hours=1),
        )
        self.client.force_authenticate(self.agent)
        response = self.client.get("/api/tickets/breached/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_attachment_rejects_unsupported_extension(self):
        ticket = self.create_ticket()
        self.client.force_authenticate(self.customer)
        file_obj = SimpleUploadedFile("malware.exe", b"fake", content_type="application/octet-stream")
        response = self.client.post("/api/attachments/", {"Ticket": ticket.pk, "File": file_obj}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_dashboard_is_admin_only(self):
        self.client.force_authenticate(self.customer)
        denied = self.client.get("/api/dashboard/")
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.admin)
        allowed = self.client.get("/api/dashboard/")
        self.assertEqual(allowed.status_code, 200)
