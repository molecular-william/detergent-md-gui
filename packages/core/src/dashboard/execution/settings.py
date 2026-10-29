"""The one reader for the settings payload every adapter accepts.

The four run types had four copies of the same loop: require an object, start from the defaults, take the
choices from their own table, refuse a key nobody declared, coerce to `float`, refuse a non-finite or
out-of-bounds number, and turn the counts into `int`s. What differs between them is only the vocabulary and
the wording of a refusal, so both are arguments here and the loop is not copied. The checks a run type does
*after* reading its numbers -- a duration against its interval, a temperature against its force field, a
series of concentrations -- stay with that run type.
"""
import math


def normalize(settings, defaults, *, specs, choices=None, aliases=None, ignore_unknown=False,
              object_message='Settings must be an object', unknown_prefix='Unknown setting: ',
              label_messages=False, bool_message=None, choice_text=False, integrals=None,
              integral_in_loop=False):
    """Normalize one run type's payload against its own vocabulary.

    `specs` maps a key to `(label, low, high)`; the label is what a numeric refusal names when
    `label_messages` is set (the CG half's spelling), otherwise the key is. `choices` maps a key to
    `(label, options)`, and empty options accept any value. `aliases` maps a spelling to the key it is
    stored under. `integrals` maps a count to the message its refusal carries. `bool_message` refuses a
    boolean where a number was asked for; an adapter that has always accepted one leaves it out.
    `choice_text` stores a choice as `str`, as the osmotic settings do. `integral_in_loop` checks a count
    as soon as it is read rather than after the loop, which is how the pdc reader refuses one.

    A supplied key that is one of the defaults but has no spec is taken without a bound (`pdc.attempts_max`);
    any other key is unknown unless `ignore_unknown` says the payload also carries things that are not
    settings.
    """
    if settings is not None and not isinstance(settings, dict):
        raise ValueError(object_message)
    choices = choices or {}
    integrals = integrals or {}
    result = dict(defaults)
    for key, value in (settings or {}).items():
        name = (aliases or {}).get(key) or key
        if name in choices:
            _, options = choices[name]
            if choice_text:
                value = str(value)
            if options and value not in options:
                raise ValueError(f'{name} must be one of ' + ', '.join(str(option) for option in options))
            result[name] = value
            continue
        if name not in specs:
            if name in result:
                result[name] = value
                continue
            if ignore_unknown:
                continue
            raise ValueError(unknown_prefix + key)
        label, low, high = specs[name]
        if bool_message and isinstance(value, bool):
            raise ValueError(bool_message)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError((label if label_messages else name) + ' must be numeric') from exc
        named = label if label_messages else name
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{named} must be between {low} and {high}')
        if integral_in_loop and name in integrals:
            if number != int(number):
                raise ValueError(integrals[name])
            number = int(number)
        result[name] = number
    return coerce_integers(result, integrals)


def coerce_integers(result, integrals):
    """Check and convert the counts named in `integrals`; a fractional one is refused with its own message.

    Separate from `normalize` for the one run type that has work to do between reading its numbers and checking
    them: an osmotic run reads its concentrations first, so a ragged series is refused before a fractional
    attempt or device index is.
    """
    for name, message in integrals.items():
        if name not in result:
            continue
        value = result[name]
        if isinstance(value, float) and int(value) != value:
            raise ValueError(message)
        result[name] = int(value)
    return result
