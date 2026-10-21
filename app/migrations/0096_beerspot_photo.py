import app.domain.upload_paths
import app.storages
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0095_bar_menu'),
    ]

    operations = [
        migrations.AddField(
            model_name='beerspot',
            name='photo',
            field=models.ImageField(blank=True, null=True, storage=app.storages.spot_photos_storage, upload_to=app.domain.upload_paths.spot_photo_path, verbose_name='Photo'),
        ),
    ]
