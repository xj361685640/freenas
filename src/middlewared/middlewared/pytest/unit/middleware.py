from asynctest import Mock
from middlewared.schema import Schemas, resolve_methods


class Middleware(dict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self['system.is_freenas'] = Mock(return_value=True)
        self.__schemas = Schemas()

    async def _call(self, name, serviceobj, method, args):
        to_resolve = [getattr(serviceobj, attr) for attr in dir(serviceobj) if attr != 'query']
        resolve_methods(self.__schemas, to_resolve)
        return await method(*args)

    async def call(self, name, *args):
        return self[name](*args)

    async def run_in_thread(self, method, *args, **kwargs):
        return method(*args, **kwargs)
