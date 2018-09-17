import asyncio
import copy
import errno
import ipaddress
import os

from croniter import croniter

from middlewared.service_exception import ValidationErrors

NOT_PROVIDED = object()


class Error(Exception):

    def __init__(self, attribute, errmsg, errno=errno.EINVAL):
        self.attribute = attribute
        self.errmsg = errmsg
        self.errno = errno
        self.extra = None

    def __str__(self):
        return '[{0}] {1}'.format(self.attribute, self.errmsg)


class EnumMixin(object):

    def __init__(self, *args, **kwargs):
        self.enum = kwargs.pop('enum', None)
        super(EnumMixin, self).__init__(*args, **kwargs)

    def clean(self, value):
        value = super().clean(value)
        if self.enum is None:
            return value
        if not isinstance(value, (list, tuple)):
            tmp = [value]
        else:
            tmp = value
        for v in tmp:
            if v not in self.enum:
                raise Error(self.name, f'Invalid choice: {value}')
        return value


class Attribute(object):

    def __init__(self, name, title=None, description=None, required=False, null=False, empty=True, private=False,
                 validators=None, register=False, **kwargs):
        self.name = name
        self.has_default = 'default' in kwargs
        self.default = kwargs.pop('default', None)
        self.required = required
        self.null = null
        self.empty = empty
        self.private = private
        self.title = title or name
        self.description = description
        self.validators = validators or []
        self.register = register

    def clean(self, value):
        if value is None and self.null is False:
            raise Error(self.name, 'null not allowed')
        if value is NOT_PROVIDED:
            if self.has_default:
                return copy.deepcopy(self.default)
            else:
                raise Error(self.name, 'attribute required')
        return value

    def dump(self, value):
        if self.private:
            return "********"

        return value

    def validate(self, value):
        verrors = ValidationErrors()

        for validator in self.validators:
            try:
                validator(value)
            except ValueError as e:
                verrors.add(self.name, str(e))

        if verrors:
            raise verrors

    def to_json_schema(self, parent=None):
        """This method should return the json-schema v4 equivalent for the
        given attribute.
        """
        raise NotImplementedError("Attribute must implement to_json_schema method")

    def resolve(self, middleware):
        """
        After every plugin is initialized this method is called for every method param
        so that the real attribute is evaluated.
        e.g.
        @params(
            Patch('schema-name', 'new-name', ('add', {'type': 'string', 'name': test'})),
            Ref('schema-test'),
        )
        will resolve to:
        @params(
            Dict('new-name', ...)
            Dict('schema-test', ...)
        )
        """
        if self.register:
            middleware.add_schema(self)
        return self


class Any(Attribute):

    def to_json_schema(self, parent=None):
        schema = {
            'anyOf': [
                {'type': 'string'},
                {'type': 'integer'},
                {'type': 'boolean'},
                {'type': 'object'},
                {'type': 'array'},
            ],
            'title': self.title,
        }
        if self.description:
            schema['description'] = self.description
        if not parent:
            schema['_required_'] = self.required
        return schema


class Str(EnumMixin, Attribute):

    def clean(self, value):
        value = super(Str, self).clean(value)
        if value is None:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise Error(self.name, 'Not a string')
        if not self.empty and not value:
            raise Error(self.name, 'Empty value not allowed')
        return value

    def to_json_schema(self, parent=None):
        schema = {}
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        if not self.required:
            schema['type'] = ['string', 'null']
        else:
            schema['type'] = 'string'
        if self.enum is not None:
            schema['enum'] = self.enum
        return schema


class Dir(Str):

    def validate(self, value):
        if value is None:
            return

        verrors = ValidationErrors()

        if value:
            if not os.path.exists(value):
                verrors.add(self.name, "This path does not exist.", errno.ENOENT)
            elif not os.path.isdir(value):
                verrors.add(self.name, "This path is not a directory.", errno.ENOTDIR)

        if verrors:
            raise verrors

        return super().validate(value)


class File(Str):

    def validate(self, value):
        if value is None:
            return

        verrors = ValidationErrors()

        if value:
            if not os.path.exists(value):
                verrors.add(self.name, "This path does not exist.", errno.ENOENT)
            elif not os.path.isfile(value):
                verrors.add(self.name, "This path is not a file.", errno.EISDIR)

        if verrors:
            raise verrors

        return super().validate(value)


class IPAddr(Str):

    def __init__(self, *args, **kwargs):
        self.cidr = kwargs.pop('cidr', False)
        self.network = kwargs.pop('network', False)
        self.network_strict = kwargs.pop('network_strict', False)

        self.v4 = kwargs.pop('v4', True)
        self.v6 = kwargs.pop('v6', True)

        if self.v4 and self.v6:
            if self.network:
                self.factory = ipaddress.ip_network
            elif self.cidr:
                self.factory = ipaddress.ip_interface
            else:
                self.factory = ipaddress.ip_address
        elif self.v4:
            if self.network:
                self.factory = ipaddress.IPv4Network
            elif self.cidr:
                self.factory = ipaddress.IPv4Interface
            else:
                self.factory = ipaddress.IPv4Address
        elif self.v6:
            if self.network:
                self.factory = ipaddress.IPv6Network
            elif self.cidr:
                self.factory = ipaddress.IPv6Interface
            else:
                self.factory = ipaddress.IPv6Address
        else:
            raise ValueError("Either IPv4 or IPv6 should be allowed")

        self.allow_zone_index = kwargs.pop('allow_zone_index', False)

        super(IPAddr, self).__init__(*args, **kwargs)

    def validate(self, value):
        if value is None:
            return

        verrors = ValidationErrors()

        if value:
            try:
                if self.network:
                    self.factory(value, strict=self.network_strict)
                else:
                    if self.cidr and '/' not in value:
                        raise ValueError(
                            'Specified address should be in CIDR notation, e.g. 192.168.0.2/24'
                        )

                    has_zone_index = False
                    if self.allow_zone_index and "%" in value:
                        has_zone_index = True
                        value = value[:value.rindex("%")]

                    addr = self.factory(value)

                    if has_zone_index and not isinstance(addr, ipaddress.IPv6Address):
                        raise ValueError("Zone index is allowed only for IPv6 addresses")
            except ValueError as e:
                verrors.add(self.name, str(e), errno.EINVAL)

        if verrors:
            raise verrors

        return super().validate(value)


class Bool(Attribute):

    def clean(self, value):
        value = super().clean(value)
        if value is None:
            return value
        if not isinstance(value, bool):
            raise Error(self.name, 'Not a boolean')
        return value

    def to_json_schema(self, parent=None):
        schema = {
            'type': ['boolean', 'null'] if not self.required else 'boolean',
        }
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        return schema


class Int(EnumMixin, Attribute):

    def clean(self, value):
        value = super(Int, self).clean(value)
        if value is None:
            return value
        if not isinstance(value, int) or isinstance(value, bool):
            if isinstance(value, str) and value.isdigit():
                return int(value)
            raise Error(self.name, 'Not an integer')
        return value

    def to_json_schema(self, parent=None):
        schema = {
            'type': ['integer', 'null'] if not self.required else 'integer',
        }
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        return schema


class Float(EnumMixin, Attribute):

    def clean(self, value):
        value = super(Float, self).clean(value)
        if value is None and not self.required:
            return self.default
        try:
            # float(False) = 0.0
            # float(True) = 1.0
            if isinstance(value, bool):
                raise TypeError()
            return float(value)
        except (TypeError, ValueError):
            raise Error(self.name, 'Not a floating point number')

    def to_json_schema(self, parent=None):
        schema = {
            'type': ['float', 'null'] if not self.required else 'float',
        }
        if not parent:
            schema['title'] = self.verbose
            schema['_required_'] = self.required
        return schema


class List(EnumMixin, Attribute):

    def __init__(self, *args, **kwargs):
        self.items = kwargs.pop('items', [])
        self.unique = kwargs.pop('unique', False)
        super(List, self).__init__(*args, **kwargs)

    def clean(self, value):
        value = super(List, self).clean(value)
        if value is None:
            return copy.deepcopy(self.default)
        if not isinstance(value, list):
            raise Error(self.name, 'Not a list')
        if not self.empty and not value:
            raise Error(self.name, 'Empty value not allowed')
        if self.items:
            for index, v in enumerate(value):
                for i in self.items:
                    try:
                        value[index] = i.clean(v)
                        found = True
                    except Error as e:
                        found = e
                        break
                if self.items and found is not True:
                    raise Error(self.name, 'Item#{0} is not valid per list types: {1}'.format(index, found))
        return value

    def dump(self, value):
        if self.private or (self.items and any(item.private for item in self.items)):
            return "********"

        return value

    def validate(self, value):
        if value is None:
            return

        verrors = ValidationErrors()

        s = set()
        for i, v in enumerate(value):
            if self.unique:
                if v in s:
                    verrors.add(f"{self.name}.{i}", "This value is not unique.")
                s.add(v)
            for attr in self.items:
                try:
                    attr.validate(v)
                except ValidationErrors as e:
                    verrors.add_child(f"{self.name}.{i}", e)

        if verrors:
            raise verrors

        super().validate(value)

    def to_json_schema(self, parent=None):
        schema = {'type': 'array'}
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        if self.required:
            schema['type'] = ['array', 'null']
        else:
            schema['type'] = 'array'
        if self.enum is not None:
            schema['enum'] = self.enum
        items = []
        for i in self.items:
            child_schema = i.to_json_schema(self)
            if isinstance(child_schema['type'], list):
                for t in child_schema['type']:
                    items.append({'type': t})
                    break
            else:
                items.append({'type': child_schema['type']})
        if not items:
            items.append({'type': 'null'})
        schema['items'] = items
        return schema

    def resolve(self, middleware):
        for index, i in enumerate(self.items):
            self.items[index] = i.resolve(middleware)
        if self.register:
            middleware.add_schema(self)
        return self


class Dict(Attribute):

    def __init__(self, name, *attrs, **kwargs):
        self.additional_attrs = kwargs.pop('additional_attrs', False)
        # Update property is used to disable requirement on all attributes
        # as well to not populate default values for not specified attributes
        self.update = kwargs.pop('update', False)
        if 'default' not in kwargs:
            kwargs['default'] = {}
        super(Dict, self).__init__(name, **kwargs)
        self.attrs = {}
        for i in attrs:
            self.attrs[i.name] = i

    def clean(self, data):
        data = super().clean(data)

        if data is None:
            return copy.deepcopy(self.default)

        self.errors = []
        if not isinstance(data, dict):
            raise Error(self.name, 'A dict was expected')

        for key, value in list(data.items()):
            if not self.additional_attrs:
                if key not in self.attrs:
                    raise Error(key, 'Field was not expected')

            attr = self.attrs.get(key)
            if not attr:
                continue

            data[key] = attr.clean(value)

        # Do not make any field and required and not populate default values
        if not self.update:
            for attr in list(self.attrs.values()):
                if attr.name not in data and (
                    attr.required or attr.has_default
                ):
                    data[attr.name] = attr.clean(NOT_PROVIDED)

        return data

    def dump(self, value):
        if self.private:
            return "********"

        if not isinstance(value, dict):
            return value

        value = value.copy()
        for key in value:
            attr = self.attrs.get(key)
            if not attr:
                continue

            value[key] = attr.dump(value[key])

        return value

    def validate(self, value):
        if value is None:
            return

        verrors = ValidationErrors()

        for attr in self.attrs.values():
            if attr.name in value:
                try:
                    attr.validate(value[attr.name])
                except ValidationErrors as e:
                    verrors.add_child(self.name, e)

        if verrors:
            raise verrors

    def to_json_schema(self, parent=None):
        schema = {
            'type': 'object',
            'properties': {},
            'additionalProperties': self.additional_attrs,
        }
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        for name, attr in list(self.attrs.items()):
            schema['properties'][name] = attr.to_json_schema(parent=self)
        return schema

    def resolve(self, middleware):
        for name, attr in list(self.attrs.items()):
            self.attrs[name] = attr.resolve(middleware)
        if self.register:
            middleware.add_schema(self)
        return self


class Cron(Dict):

    FIELDS = ['minute', 'hour', 'dom', 'month', 'dow']

    def __init__(self, name, **kwargs):
        self.additional_attrs = kwargs.pop('additional_attrs', False)
        # Update property is used to disable requirement on all attributes
        # as well to not populate default values for not specified attributes
        self.update = kwargs.pop('update', False)
        super(Cron, self).__init__(name, **kwargs)
        self.attrs = {}
        for i in Cron.FIELDS:
            self.attrs[i] = Str(i)

    @staticmethod
    def convert_schedule_to_db_format(data_dict, schedule_name='schedule'):
        schedule = data_dict.pop(schedule_name, None)
        if schedule:
            db_fields = ['minute', 'hour', 'daymonth', 'month', 'dayweek']
            for index, field in enumerate(Cron.FIELDS):
                if field in schedule:
                    data_dict[db_fields[index]] = schedule[field]

    @staticmethod
    def convert_db_format_to_schedule(data_dict, schedule_name='schedule'):
        db_fields = ['minute', 'hour', 'daymonth', 'month', 'dayweek']
        data_dict[schedule_name] = {}
        for index, field in enumerate(db_fields):
            if field in data_dict:
                data_dict[schedule_name][Cron.FIELDS[index]] = data_dict.pop(field)

    def validate(self, value):
        verrors = ValidationErrors()

        for attr in self.attrs.values():
            if attr.name in value:
                try:
                    attr.validate(value[attr.name])
                except ValidationErrors as e:
                    verrors.add_child(self.name, e)

        for v in value:
            if v not in Cron.FIELDS:
                verrors.add(self.name, f'Unexpected {v} value')

        if verrors:
            raise verrors

        cron_expression = ''
        for field in Cron.FIELDS:
            cron_expression += value.get(field) + ' ' if value.get(field) else '* '

        try:
            croniter(cron_expression)
        except Exception as e:
            verrors.add(self.name, 'Please ensure fields match cron syntax - ' + str(e))

        if verrors:
            raise verrors


class Ref(object):

    def __init__(self, name):
        self.name = name

    def resolve(self, middleware):
        schema = middleware.get_schema(self.name)
        if not schema:
            raise ResolverError('Schema {0} does not exist'.format(self.name))
        schema = copy.deepcopy(schema)
        schema.register = False
        return schema


class Patch(object):

    def __init__(self, name, newname, *patches, register=False):
        self.name = name
        self.newname = newname
        self.patches = patches
        self.register = register

    def convert(self, spec):
        t = spec.pop('type')
        name = spec.pop('name')
        if t in ('int', 'integer'):
            return Int(name, **spec)
        elif t in ('str', 'string'):
            return Str(name, **spec)
        elif t in ('bool', 'boolean'):
            return Bool(name, **spec)
        elif t == 'dict':
            return Dict(name, **spec)
        raise ValueError('Unknown type: {0}'.format(spec['type']))

    def resolve(self, middleware):
        schema = middleware.get_schema(self.name)
        if not schema:
            raise ResolverError(f'Schema {self.name} not found')
        elif not isinstance(schema, Dict):
            raise ValueError('Patch non-dict is not allowed')

        schema = copy.deepcopy(schema)
        schema.name = self.newname
        for operation, patch in self.patches:
            if operation == 'add':
                if isinstance(patch, dict):
                    new = self.convert(dict(patch))
                else:
                    new = copy.deepcopy(patch)
                schema.attrs[new.name] = new
            elif operation == 'rm':
                del schema.attrs[patch['name']]
            elif operation == 'edit':
                attr = schema.attrs[patch['name']]
                if 'method' in patch:
                    patch['method'](attr)
            elif operation == 'attr':
                for key, val in list(patch.items()):
                    setattr(schema, key, val)
        if self.register:
            middleware.add_schema(schema)
        return schema


class ResolverError(Exception):
    pass


def resolver(middleware, f):
    if not callable(f):
        return
    if not hasattr(f, 'accepts'):
        return
    new_params = []
    for p in f.accepts:
        if isinstance(p, (Patch, Ref, Attribute)):
            new_params.append(p.resolve(middleware))
        else:
            raise ResolverError('Invalid parameter definition {0}'.format(p))

    # FIXME: for some reason assigning params (f.accepts = new_params) does not work
    f.accepts.clear()
    f.accepts.extend(new_params)


def accepts(*schema):
    def wrap(f):
        # Make sure number of schemas is same as method argument
        args_index = 1
        if hasattr(f, '_pass_app'):
            args_index += 1
        if hasattr(f, '_job'):
            args_index += 1
        assert len(schema) == f.__code__.co_argcount - args_index  # -1 for self

        def clean_and_validate_args(args, kwargs):
            args = list(args)
            args = args[:args_index] + copy.deepcopy(args[args_index:])
            kwargs = copy.deepcopy(kwargs)

            verrors = ValidationErrors()

            # Iterate over positional args first, excluding self
            i = 0
            for _ in args[args_index:]:
                attr = nf.accepts[i]

                value = attr.clean(args[args_index + i])
                args[args_index + i] = value

                try:
                    attr.validate(value)
                except ValidationErrors as e:
                    verrors.extend(e)

                i += 1

            # Use i counter to map keyword argument to rpc positional
            for x in list(range(i + 1, f.__code__.co_argcount)):
                kwarg = f.__code__.co_varnames[x]

                if kwarg in kwargs:
                    attr = nf.accepts[i]
                    i += 1

                    value = kwargs[kwarg]
                elif len(nf.accepts) >= i + args_index:
                    attr = nf.accepts[i]
                    i += 1
                    value = NOT_PROVIDED
                else:
                    i += 1
                    continue

                value = attr.clean(value)
                kwargs[kwarg] = value

                try:
                    attr.validate(value)
                except ValidationErrors as e:
                    verrors.extend(e)

            if verrors:
                raise verrors

            return args, kwargs

        if asyncio.iscoroutinefunction(f):
            async def nf(*args, **kwargs):
                args, kwargs = clean_and_validate_args(args, kwargs)
                return await f(*args, **kwargs)
        else:
            def nf(*args, **kwargs):
                args, kwargs = clean_and_validate_args(args, kwargs)
                return f(*args, **kwargs)

        nf.__name__ = f.__name__
        nf.__doc__ = f.__doc__
        # Copy private attrs to new function so decorators can work on top of it
        # e.g. _pass_app
        for i in dir(f):
            if i.startswith('__'):
                continue
            if i.startswith('_'):
                setattr(nf, i, getattr(f, i))
        nf.accepts = list(schema)

        return nf
    return wrap


class UnixPerm(Str):

    def validate(self, value):
        if value is None:
            return

        try:
            mode = int(value, 8)
        except ValueError:
            raise Error('mode',
                        'Not a valid integer. Must be between 000 and 777')

        if mode & 0o777 != mode:
            raise Error('mode', 'Please supply a value between 000 and 777')
        return super().validate(value)

    def to_json_schema(self, parent=None):
        schema = {
            'type': ['string', 'null'] if not self.required else 'string',
        }
        if not parent:
            schema['title'] = self.title
            if self.description:
                schema['description'] = self.description
            schema['_required_'] = self.required
        return schema
