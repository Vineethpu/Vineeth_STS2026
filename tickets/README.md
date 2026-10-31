# STS_2026 — Support Ticket System with Roles

Django REST Framework + MySQL 8 + JWT authentication.

## Features
- Customer, Agent and Admin roles (Django Groups).
- Customers create and view their own tickets.
- Agents view tickets assigned to them.
- Admins assign and reassign agents.
- Status flow: `Open → In Progress → Resolved → Closed`.
- Customers may reopen a closed ticket within 7 days.
- Public comments and private internal notes for agents/admins.
- Ticket history records every status and assignee change.
- SLA response deadlines by priority and `/api/tickets/breached/`.
- Admin dashboard: status counts, average resolution hours per agent, tickets by category.
- Attachment validation: PDF, PNG, JPG, JPEG, TXT; maximum 5 MB.
- JWT, pagination, standardized errors, indexes, DB constraints, API tests and Swagger.

## 1. Create and activate virtual environment
Windows:
```powershell
python -m venv venv
venv\Scripts\activate
```
Linux/macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

## 2. Install packages
```bash
pip install -r requirements.txt
```

## 3. Configure environment
Copy `.env.example` to `.env` and edit database credentials and secret key.

Create the MySQL database:
```sql
CREATE DATABASE ticketdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 4. Create/update database tables
```bash
python manage.py makemigrations tickets
python manage.py migrate
```
If this is an existing database, take a backup before applying migrations.

## 5. Create admin account
```bash
python manage.py createsuperuser
```
A Django superuser automatically has Admin access. For normal users, create three Groups named exactly `Customer`, `Agent`, and `Admin`, then assign each user to the appropriate group in `/admin/`.

In Django Admin:
- Add Categories such as Technical, Billing and Account.
- Add one SLA policy per priority (example: Critical=1, High=4, Medium=8, Low=24 response hours).

## 6. Run
```bash
python manage.py runserver
```

## Authentication
`POST /api/login/`
```json
{"username": "customer1", "password": "your-password"}
```
Use the returned access token:
`Authorization: Bearer <access-token>`

Refresh:
`POST /api/token/refresh/`
```json
{"refresh": "<refresh-token>"}
```

## API endpoints
| Method | Endpoint | Access |
|---|---|---|
| POST | `/api/login/` | Public |
| POST | `/api/token/refresh/` | Public |
| GET, POST | `/api/tickets/` | All roles (POST: Customer only) |
| GET, PATCH | `/api/tickets/<id>/` | Visible ticket; PATCH follows role rules |
| GET | `/api/tickets/breached/` | Agent (assigned tickets), Admin (all) |
| GET, POST | `/api/comments/` | Visible ticket users |
| GET | `/api/history/?ticket=<id>` | Agent (assigned tickets), Admin |
| GET, POST | `/api/attachments/` | Visible ticket users |
| GET | `/api/categories/` | Admin |
| GET, POST, PATCH, DELETE | `/api/sla-policies/` | Admin |
| GET | `/api/dashboard/` | Admin |
| GET | `/api/schema/` | Authenticated API schema |
| GET | `/api/docs/` | Swagger UI |

List endpoints use page-number pagination (`?page=1`); page size defaults to 10.

## Ticket examples
Create ticket:
```json
{
  "Title": "Cannot login",
  "Description": "I cannot sign in to my account.",
  "Category": 1,
  "Priority": "High"
}
```
Admin assign agent:
```json
{"AssignedAgent": 3}
```
Agent moves status one step at a time:
```json
{"Status": "In Progress"}
```
Customer reopens a closed ticket within seven days:
```json
{"Status": "Open"}
```

Upload attachment using multipart form-data fields `Ticket` and `File`.

## Tests
```bash
python manage.py test tickets
```
The app includes more than eight `APITestCase` tests.

## Notes
- Create a separate group for each role; role names are case-sensitive.
- Assign exactly one role group to each regular user.
- The first public comment from staff or transition to In Progress satisfies the first-response SLA.
- Internal comments are hidden from customers.
- For production, configure HTTPS, secure cookies, a strong `SECRET_KEY`, proper `ALLOWED_HOSTS`, and a private media-storage service.
