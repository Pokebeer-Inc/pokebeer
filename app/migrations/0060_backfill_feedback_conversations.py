from datetime import timedelta

from django.db import migrations

from app.services.slugs import generate_slug


def forward(apps, schema_editor):
    """Donne un slug opaque à chaque feedback et transforme son ancienne « réponse de l'équipe » en message d'échange.

    La date de la réponse n'était pas conservée : elle est placée juste après le premier message du membre.
    """
    Feedback = apps.get_model('app', 'Feedback')
    FeedbackMessage = apps.get_model('app', 'FeedbackMessage')
    for feedback in Feedback.objects.all().iterator():
        feedback.slug = generate_slug('', Feedback._meta.get_field('slug').max_length)
        feedback.save(update_fields=['slug'])
        already_there = FeedbackMessage.objects.filter(feedback=feedback, author_kind='team', body=feedback.admin_reply).exists()
        if feedback.admin_reply and not already_there:  # idempotent : rejouable après un retour arrière
            reply = FeedbackMessage.objects.create(feedback=feedback, author_kind='team', body=feedback.admin_reply)
            FeedbackMessage.objects.filter(pk=reply.pk).update(created_at=feedback.created_at + timedelta(seconds=1))


def backward(apps, schema_editor):
    """Restaure `admin_reply` avec la dernière réponse de l'équipe."""
    Feedback = apps.get_model('app', 'Feedback')
    FeedbackMessage = apps.get_model('app', 'FeedbackMessage')
    for feedback in Feedback.objects.all().iterator():
        last = FeedbackMessage.objects.filter(feedback=feedback, author_kind='team').order_by('created_at', 'pk').last()
        if last:
            Feedback.objects.filter(pk=feedback.pk).update(admin_reply=last.body)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0059_conversations_and_toasts'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
