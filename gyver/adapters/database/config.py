import abc

from gyver.config import AdapterConfigFactory, as_config
from gyver.url import URL, Netloc


@as_config
class DatabaseConfig(abc.ABC):
    host: str
    port: int = -1
    user: str = ""
    password: str = ""
    name: str = ""
    pool_size: int = 20
    pool_recycle: int = 3600
    max_overflow: int = 0
    autotransaction: bool = False


db_config_factory = AdapterConfigFactory().maker(DatabaseConfig, "db")


def make_uri(config: DatabaseConfig, port: int, scheme: str) -> str:
    url = URL("")
    url.scheme = scheme
    netloc = Netloc("").set(
        host=config.host,
        port=port,
        username=config.user,
        password=config.password,
    )
    return url.set(netloc_args=netloc).encode()
