from django import forms
from django.contrib.auth import get_user_model


class AdminUserCreationForm(forms.ModelForm):
    password = forms.CharField(
        label="Initial password",
        min_length=8,
        strip=False,
        widget=forms.PasswordInput,
        help_text="The user can change this after signing in.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name", "is_active", "password")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        user.is_superuser = False
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
