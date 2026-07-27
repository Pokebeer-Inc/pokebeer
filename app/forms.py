from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import BeerUser, Beer, Brewery, Drinks, Feedback
from django.utils.text import slugify

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = BeerUser
        # Fields you want the user to fill in
        fields = ['username', 'email']

    def clean_email(self):
        # Add custom validation to ensure email is unique
        email = self.cleaned_data.get('email')
        if BeerUser.objects.filter(email=email).exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email
    
    def __init__(self, *args, **kwargs):
        super(UserRegisterForm, self).__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['email'].label = "Adresse Email"
        
        # On applique les classes visuelles et le placeholder
        for field_name, field in self.fields.items():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class UserLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super(UserLoginForm, self).__init__(*args, **kwargs)
        
        # On définit explicitement les labels
        self.fields['username'].label = "Pseudo"
        self.fields['password'].label = "Mot de passe"
        
        # On applique les classes visuelles et le placeholder
        for field_name, field in self.fields.items():
            
            field.widget.attrs.update({
                'class': 'input input-bordered w-full bg-white/80 focus:bg-white transition-colors'
            })

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['username', 'email', 'bio']
        labels = {
            'username': "Nom d'utilisateur",
            'email': "Adresse Email",
            'bio': "Ma Biographie"
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Parlez-nous de vos goûts brassicoles...'})
        }

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;'
            })

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # On vérifie si l'email existe déjà chez un AUTRE utilisateur (exclure self.instance)
        if BeerUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un autre membre.")
        return email

class BeerForm(forms.ModelForm):
    brewery_name = forms.CharField(
        label='Brasserie',
        help_text="Tapez le nom. Si elle n'existe pas, elle sera créée.",
        widget=forms.TextInput(attrs={'autocomplete': 'off'})
    )

    class Meta:
        model = Beer
        fields = ['name', 'brewery_name', 'style', 'description', 'bitterness', 'degree']
        labels = {
            'name': 'Nom de la bière',
            'description': 'Description',
            'bitterness': 'Amertume (IBU)',
            'degree': 'Degré d\'alcool (%)',
            'style': 'Style de bière',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'name': forms.TextInput(attrs={'autocomplete': 'off'})
        }

    def __init__(self, *args, **kwargs):
        # Pré-remplir le champ 'brewery_name' si on est en mode édition (instance existante)
        if 'instance' in kwargs and kwargs['instance'] and kwargs['instance'].brewery_id:
            initial = kwargs.setdefault('initial', {})
            initial['brewery_name'] = kwargs['instance'].brewery_id.name
            
        super(BeerForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;'
            })

    def save(self, user=None, commit=True):
        beer = super(BeerForm, self).save(commit=False)
        b_name = self.cleaned_data['brewery_name']
        brewery, created = Brewery.objects.get_or_create(
            name__iexact=b_name,
            defaults={'name': b_name, 'city': 'Inconnue', 'description': 'Ajoutée automatiquement'}
        )
        beer.brewery_id = brewery
        
        if user:
            beer.added_by = user
            
        if commit:
            beer.save()
        return beer
    
    def clean_name(self):
        """Bouclier anti-doublon insensible à la casse, espaces, et accents"""
        name = self.cleaned_data.get('name')
        if name:
            # On transforme le nom tapé en slug (ex: "Pünk I.P.A " devient "punk-ipa")
            normalized_name = slugify(name)
            # On ignore les bières supprimées dans la vérification des doublons
            existing_beer = Beer.objects.filter(slug=normalized_name, is_deleted=False).first()
            if existing_beer:
                # Si on est en mode modification et que c'est notre propre bière, on laisse passer
                if self.instance and self.instance.pk == existing_beer.pk:
                    pass
                else:
                    raise forms.ValidationError(f"Cette bière existe déjà sous le nom '{existing_beer.name}'")
        return name
    
    def clean_style(self):
        style = self.cleaned_data.get('style')
        if style:
            # Sépare par la virgule, enlève les espaces inutiles, et met une majuscule à chaque style
            styles = [s.strip().capitalize() for s in style.split(',') if s.strip()]
            # Reconstruit une belle chaîne "Style 1, Style 2"
            return ", ".join(styles)
        return style
    
class DrinkForm(forms.ModelForm):
    class Meta:
        model = Drinks
        fields = ['date', 'note', 'comment']
        labels = {
            'date': 'Date de dégustation',
            'note': 'Note (sur 10)',
            'comment': 'Mon avis personnel'
        }
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Votre expérience, vos impressions en toute subjectivité...', 'class': 'textarea textarea-bordered w-full'}),
            'note': forms.NumberInput(attrs={'min': 0, 'max': 10}),
        }

    def __init__(self, *args, **kwargs):
        super(DrinkForm, self).__init__(*args, **kwargs)
        # Style uniforme pour faire "Pro"
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px;'
            })
            
class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ['message']
        labels = {
            'message': "Votre suggestion, remarque ou bug"
        }
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4})
        }

    def __init__(self, *args, **kwargs):
        super(FeedbackForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;'
            })
            
class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['notif_global', 'notif_follow', 'notif_social', 'notif_network', 'notif_achievements']
        widgets = {
            'notif_global': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
            'notif_follow': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_social': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_network': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
            'notif_achievements': forms.CheckboxInput(attrs={'class': 'toggle toggle-sm toggle-primary'}),
        }