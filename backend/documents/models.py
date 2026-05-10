import uuid
from django.db import models
from django.conf import settings

def user_directory_path(instance, filename):
    return f'uploads/user_{instance.user.id}/{filename}'

class Document(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    # Use UUID for non-incremental, user-specific identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='documents'
    )
    file = models.FileField(upload_to=user_directory_path)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10) 
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.file_name