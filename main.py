import pandas as pd
from shared_config.sqlserver import PROD_SERVER, PYRO_DATABASE
from shared_utils.sharepoint import load_sharepoint_export
from shared_utils.sqlserver import get_engine
from sqlalchemy.schema import CreateSchema

import config
from transform import build_tables


def main():
    raw = {key: load_sharepoint_export(name, config.DATA_DIR) for key, name in config.LISTS.items()}
    now = pd.Timestamp.now(tz=config.LOCAL_TZ).strftime('%Y-%m-%d %H:%M')
    tables = build_tables(raw['requests'], raw['costs'], raw['volumes'], now)

    engine = get_engine(PROD_SERVER, PYRO_DATABASE)
    with engine.connect() as conn:
        if not conn.dialect.has_schema(conn, config.SCHEMA):
            conn.execute(CreateSchema(config.SCHEMA))
        conn.commit()

    for name, df in tables.items():
        df.to_sql(name=name, con=engine, schema=config.SCHEMA, if_exists='replace', index=False)


if __name__ == '__main__':
    main()
