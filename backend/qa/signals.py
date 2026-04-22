
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F
from .models import QuestionActivity
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(post_save, sender=QuestionActivity)
def increment_question_count(sender, instance, created, **kwargs):
    """
    Automatically increment user's question_count
    whenever a new QuestionActivity is created.
    """
    if created:
        User.objects.filter(id=instance.user_id).update(
            question_count=F('question_count') + 1
        )