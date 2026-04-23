from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    return d.get(key)

@register.filter
def as_p_form(form):
    return form.as_p()


@register.filter
def shares_center_with(user, coordinator):
    if not user or not coordinator:
        return False

    user_centros = getattr(user, "centros", None)
    coordinator_centros = getattr(coordinator, "centros", None)
    if user_centros is None or coordinator_centros is None:
        return False

    return coordinator_centros.filter(
        id__in=user_centros.values_list("id", flat=True)
    ).exists()
