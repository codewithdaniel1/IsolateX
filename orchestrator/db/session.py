from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from .models import Base
from orchestrator.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
