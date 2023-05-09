import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.dialects.oracle
import sqlalchemy.dialects.sqlite


IDInteger = sqlalchemy.BigInteger().with_variant(sqlalchemy.dialects.sqlite.INTEGER(), "sqlite")
Float = (
    sqlalchemy.Float(53)
    .with_variant(sqlalchemy.dialects.sqlite.REAL(), "sqlite")
    .with_variant(sqlalchemy.dialects.oracle.BINARY_DOUBLE(), "oracle")
)


type_map_override = {str: sqlalchemy.Text(), float: Float}


class MaybeEncrypted:
    release_tag: sqlalchemy.orm.Mapped[str | None] = sqlalchemy.orm.mapped_column()
    _encryption_release_id: sqlalchemy.orm.Mapped[int | None] = sqlalchemy.orm.mapped_column()
