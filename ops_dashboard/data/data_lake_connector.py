from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from ops_dashboard.data.database import query_metrics, get_available_filters


class DataLakeConnector(ABC):
    """Abstract interface for Data Lake connectivity.
    Swap implementations to switch from mock data to Snowflake/BigQuery/Databricks."""

    @abstractmethod
    def query(self, site=None, product_line=None, time_range="30d",
              date_from=None, date_to=None) -> List[Dict]:
        pass

    @abstractmethod
    def get_dimensions(self) -> Dict[str, List[str]]:
        pass


class MockDataLakeConnector(DataLakeConnector):
    """Implementation that reads from the local SQLite mock database."""

    def query(self, site=None, product_line=None, time_range="30d",
              date_from=None, date_to=None) -> List[Dict]:
        return query_metrics(site, product_line, time_range, date_from, date_to)

    def get_dimensions(self) -> Dict[str, List[str]]:
        return get_available_filters()


# Future implementations:
# class SnowflakeConnector(DataLakeConnector): ...
# class DatabricksConnector(DataLakeConnector): ...
# class BigQueryConnector(DataLakeConnector): ...
