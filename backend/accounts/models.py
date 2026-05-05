import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Extends AbstractUser so we keep all Django auth
    goodness (password hashing, permissions, admin) while being free
    to add RAG-specific fields without a painful migration later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]

    def __str__(self):
        return self.email or self.username