from django import template


register = template.Library()


@register.filter(is_safe=True)
def accessible_field(bound_field):
    described_by = []
    if bound_field.help_text:
        described_by.append(f"{bound_field.auto_id}_helptext")
    attrs = {}
    if bound_field.errors:
        attrs["aria-invalid"] = "true"
        described_by.append(f"{bound_field.auto_id}_errors")
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)
    return bound_field.as_widget(attrs=attrs)
