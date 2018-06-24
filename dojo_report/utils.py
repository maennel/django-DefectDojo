import logging
from datetime import datetime, date, time
from numbers import Number

import six
from django.contrib.auth.models import AbstractUser
from django.db import models

logger = logging.getLogger(__name__)


def is_iterable(x):
    try:
        iter(x)
    except TypeError:
        return False
    return True


def convert_model_typed_object(obj, exclude_fields=[], include_fields=[]):
    """
    Convert objects having Django's Model class as a base class to native
    types. ``include_fields`` takes precedence over ``exclude_fields``,
    meaning, if include_fields is specified, exclude_fields is ignored.
    :param obj: the object (of a Model type) to be converted to native data types
    :param list exclude_fields: a list of field names (strings) to be excluded
    :param list include_fields: a list of field names to be included
    :return: a new dict holding the native data-type object
    """
    if not include_fields:
        all_fields = {f.name for f in obj._meta.local_fields}
        include_fields = all_fields.difference(set(exclude_fields))

    return {f_name: convert_to_native_type(getattr(obj, f_name)) for
            f_name in include_fields}


def convert_to_native_type(obj, ignore_errors=False):
    """
    Convert complex, non-serializable objects to native data types
    :param obj: a python object of a given type
    :return: a representation with native data types of the given object
    """
    if obj is None:
        return None
    if isinstance(obj, six.string_types) or isinstance(obj, Number):
        return obj
    if isinstance(obj, dict):
        return {
            convert_to_native_type(k): convert_to_native_type(v) for
            k, v in obj.items()}
    if is_iterable(obj):
        return [convert_to_native_type(part) for part in obj]
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%dT%H:%M:%S')
    if isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    if isinstance(obj, time):
        return obj.strftime('%H:%M:%S')
    if isinstance(obj, AbstractUser):
        return convert_model_typed_object(obj, exclude_fields=['password'])
    if isinstance(obj, models.Model):
        return convert_model_typed_object(obj)

    msg = "Unhandled object type detected: %s" % str(type(obj))
    logger.warning(msg)
    if not ignore_errors:
        raise ValueError(msg)
