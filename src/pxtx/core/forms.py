from django import forms
from django.utils.text import slugify

from pxtx.core.models import Comment, Issue, Milestone, Status


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = (
            "title",
            "description",
            "priority",
            "effort_minutes",
            "status",
            "blocked_reason",
            "milestone",
            "assignee",
            "is_highlighted",
            "source",
        )
        widgets = {
            "title": forms.TextInput(attrs={"autofocus": True}),
            "description": forms.Textarea(attrs={"rows": 10}),
            "blocked_reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["milestone"].queryset = Milestone.objects.order_by(
            "-target_date", "name"
        )
        self.fields["milestone"].required = False
        self.fields["milestone"].empty_label = "— none —"
        self.fields["blocked_reason"].required = False
        self.fields["description"].required = False

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        reason = cleaned.get("blocked_reason", "")
        if status == Status.BLOCKED and not reason.strip():
            self.add_error(
                "blocked_reason", "A reason is required when status is blocked."
            )
        elif status != Status.BLOCKED:
            cleaned["blocked_reason"] = ""
        return cleaned


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ("name", "slug", "description", "target_date")
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "description": forms.Textarea(attrs={"rows": 6}),
            "target_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Auto-generated from the name if empty."

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        if slug:
            return slug
        return slugify(self.cleaned_data.get("name") or "")[:50]


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {"body": forms.Textarea(attrs={"rows": 4, "placeholder": "Comment…"})}


class DescriptionForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ("description",)
        widgets = {"description": forms.Textarea(attrs={"rows": 10, "autofocus": True})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
