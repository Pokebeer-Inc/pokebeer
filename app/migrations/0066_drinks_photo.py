import app.services.tasting_photos
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0065_policy_notice'),
    ]

    operations = [
        migrations.AddField(
            model_name='drinks',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to=app.services.tasting_photos.tasting_photo_path, verbose_name='Photo'),
        ),
    ]
