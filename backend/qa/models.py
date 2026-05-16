from django.db import models
from django.conf import settings
from documents.models import Document


class QuestionActivity(models.Model):
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('no_answer', 'No Relevant Info'),
        ('error', 'Error'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='questions'
    )
    document = models.ForeignKey(
        Document, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='questions'
    )
    task_id = models.UUIDField(null=True, blank=True, db_index=True)
    question = models.TextField()
    answer = models.TextField()
    sources = models.JSONField(default=list)
    response_time_ms = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='success')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['document', 'user']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.question[:50]}"