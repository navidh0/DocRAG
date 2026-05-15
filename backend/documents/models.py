import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

def user_directory_path(instance, filename):
    return f'uploads/user_{instance.user.id}/{filename}'

class Document(models.Model):

    class Status(models.TextChoices):
        PENDING    = 'pending',    'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED  = 'completed',  'Completed'
        FAILED     = 'failed',     'Failed'

    class FileType(models.TextChoices):
        PDF  = 'pdf',  'PDF'
        XLSX = 'xlsx', 'XLSX'
        XLS  = 'xls',  'XLS'
        TXT  = 'txt',  'TXT'
        CSV  = 'csv',  'CSV'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    file      = models.FileField(upload_to=user_directory_path)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=4, choices=FileType.choices)
    status    = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.file_name