from typing import List, Optional, Any, Dict, Union
from typing import List, Optional
from datetime import datetime, date
import json
from .attribute import AsterixPredicate

class AsterixQueryBuilder:
    """Builds SQL++ queries for AsterixDB."""
    
    def __init__(self):
        self.select_cols: List[str] = []
        self.where_clauses: List[AsterixPredicate] = []
        self.group_by_columns: List[str] = []
        self.aggregates: Dict[str, str] = {}
        self.order_by_columns: List[Dict[str, Union[str, bool]]] = []
        self.unnest_clauses: List[str] = []
        self.joins: List[Dict[str, Any]] = []  # To store JOIN clauses
        self.from_dataset: Optional[str] = None
        self.limit_val: Optional[int] = None
        self.offset_val: Optional[int] = None
        self.alias = "t"  # Default table alias
        self.current_dataverse: Optional[str] = None
        self.current_alias = None

    def _get_current_alias(self) -> str:
        """Get the current table alias to use."""
        return self.current_alias or self.alias
    
    def reset_where(self):
        """Reset where clauses."""
        self.where_clauses = []
        
    def from_table(self, dataset: str) -> 'AsterixQueryBuilder':
        """Set the dataset and extract dataverse if provided."""
        if '.' in dataset:
            self.current_dataverse, self.from_dataset = dataset.split('.')
        else:
            self.from_dataset = dataset
        return self
        
    def select(self, columns: List[str]) -> 'AsterixQueryBuilder':
        """Set the columns to select."""
        self.select_cols = columns
        return self
        
    def where(self, predicate: AsterixPredicate) -> 'AsterixQueryBuilder':
        """Add a WHERE clause."""
        if predicate.is_compound:
            if predicate.left_pred:
                self._ensure_correct_alias(predicate.left_pred)
            if predicate.right_pred:
                self._ensure_correct_alias(predicate.right_pred)
        else:
            self._ensure_correct_alias(predicate)
        
        self.where_clauses.append(predicate)
        return self

    def _ensure_correct_alias(self, predicate: AsterixPredicate) -> None:
        """Ensure predicate has correct alias based on its dataset."""
        if hasattr(predicate, 'parent') and predicate.parent:
            dataset = predicate.parent.dataset
            if 'Businesses' in dataset:
                predicate.update_alias('b')
            elif 'Reviews' in dataset:
                predicate.update_alias('r')

    def _update_predicate_alias(self, predicate: AsterixPredicate):
        """Helper method to update predicate alias based on joins."""
        if hasattr(predicate, 'parent') and predicate.parent:
            dataset = predicate.parent.dataset
            for join in self.joins:
                if dataset == join['right_table']:
                    predicate.update_alias(join['alias_right'])
                    break
                elif dataset == self.from_dataset:
                    predicate.update_alias(join['alias_left'])
                    break

    def _build_where_clause(self) -> str:
        """Build the WHERE clause."""
        if not self.where_clauses:
            return ""
            
        clauses = []
        for pred in self.where_clauses:
            correct_alias = pred.get_correct_alias()
            clauses.append(pred.to_sql(correct_alias))
        
        return " AND ".join(clauses)


    def limit(self, n: int) -> 'AsterixQueryBuilder':
        """Set the LIMIT clause."""
        self.limit_val = n
        return self

    def offset(self, n: int) -> 'AsterixQueryBuilder':
        """Set the OFFSET clause."""
        self.offset_val = n
        return self

    def groupby(self, columns: Union[str, List[str]]) -> 'AsterixQueryBuilder':
        """Add GROUP BY clause to query."""
        if isinstance(columns, str):
            self.group_by_columns = [columns]
        else:
            self.group_by_columns = columns
        return self

    def _build_group_by_clause(self) -> str:
        """Build the GROUP BY clause."""
        if not self.group_by_columns:
            return ""
            
        current_alias = self._get_current_alias()    
        group_cols = []
        
        for col in self.group_by_columns:
            # If the column is a complete expression, use it as-is
            if '(' in col or ' AS ' in col:
                group_cols.append(col.split(' AS ')[0].strip())
                continue
                
            # Check for aliases from SELECT or UNNEST
            select_aliases = {
                sel.split(' AS ')[-1].strip(): sel.split(' AS ')[0].strip()
                for sel in self.select_cols if ' AS ' in sel
            }
            
            unnest_aliases = {
                unnest.split(' AS ')[-1].strip(): unnest.split(' AS ')[0].strip()
                for unnest in self.unnest_clauses
            }
            
            if col in select_aliases:
                group_cols.append(select_aliases[col])
            elif col in unnest_aliases:
                group_cols.append(col)  # Use unnest alias directly
            else:
                group_cols.append(f"{current_alias}.{col}")
                
        return f"GROUP BY {', '.join(group_cols)}"

    def aggregate(self, aggregates: Dict[str, str]) -> 'AsterixQueryBuilder':
        """
        Add aggregate functions to the query.
        
        Args:
            aggregates: Dictionary mapping field names to aggregate functions
        """
        self.aggregates = {
            col: func.upper() 
            for col, func in aggregates.items()
        }
        return self

    def _build_select_clause(self) -> str:
        """Build the SELECT clause."""
        if not self.select_cols:
            return f"SELECT VALUE {self.alias}"  # Default behavior
        select_parts = []
        for col in self.select_cols:
            if " AS " in col:
                select_parts.append(col)
            else:
                prefix = col.split(".")[0] if "." in col else self._get_current_alias()
                select_parts.append(f"{prefix}.{col}")
        return f"SELECT {', '.join(select_parts)}"


    def order_by(self, columns: Union[str, List[str], Dict[str, bool]], desc: bool = False) -> 'AsterixQueryBuilder':
        """
        Add ORDER BY clause to query.
        
        Args:
            columns: Column(s) to order by. Can be:
                    - string: single column
                    - list: multiple columns
                    - dict: column to sort direction mapping
            desc: Default sort direction if not using dict
        """
        if isinstance(columns, str):
            # Single column
            self.order_by_columns.append({
                "column": columns,
                "desc": desc
            })
        elif isinstance(columns, list):
            # Multiple columns, same direction
            for col in columns:
                self.order_by_columns.append({
                    "column": col,
                    "desc": desc
                })
        elif isinstance(columns, dict):
            # Column to direction mapping
            for col, is_desc in columns.items():
                self.order_by_columns.append({
                    "column": col,
                    "desc": is_desc
                })
        return self

    def _build_order_by_clause(self) -> str:
        """Build ORDER BY clause with proper field references."""
        if not self.order_by_columns:
            return ""
            
        order_parts = []
        for col_info in self.order_by_columns:
            col = col_info["column"]
            is_desc = col_info["desc"]
            
            # If the column is an alias (from SELECT AS) or an aggregate result,
            # use it directly without table prefix
            if any(col == sel.split(' AS ')[-1].strip() for sel in self.select_cols):
                # Column is an alias defined in SELECT
                order_parts.append(f"{col} {'DESC' if is_desc else 'ASC'}")
            elif col in {agg.split(' AS ')[-1].strip() for agg in self.select_cols if ' AS ' in agg}:
                # Column is an aggregate alias
                order_parts.append(f"{col} {'DESC' if is_desc else 'ASC'}")
            else:
                # Regular column needs table prefix
                qualified_col = f"{self.alias}.{col}" if '.' not in col else col
                order_parts.append(f"{qualified_col} {'DESC' if is_desc else 'ASC'}")
                
        return "ORDER BY " + ", ".join(order_parts)
                
    def add_unnest(
        self, 
        field: str, 
        alias: str, 
        function: Optional[str] = None,
        table_alias: Optional[str] = None
    ) -> None:
        """Add UNNEST clause to query."""
        if not table_alias:
            table_alias = self.alias
            
        if function:
            # Function is already properly formatted with correct alias
            self.unnest_clauses.append(f"UNNEST {function} AS {alias}")
        else:
            # Use provided table alias for field reference
            self.unnest_clauses.append(f"UNNEST {table_alias}.{field} AS {alias}")

    def _build_unnest_clause(self) -> str:
        """Build the UNNEST clause."""
        return " ".join(self.unnest_clauses)

    def add_join(
        self,
        right_table: str,
        on: str,
        alias_left: str,
        alias_right: str
    ) -> None:
        """
        Add a join to the query.

        Args:
            right_table: The name of the table to join with.
            on: The column to join on.
            alias_left: Alias for the left dataset.
            alias_right: Alias for the right dataset.
        """
        if not hasattr(self, "joins"):
            self.joins = []
        self.joins.append({
            "right_table": right_table,
            "on": on,
            "alias_left": alias_left,
            "alias_right": alias_right
        })


    def join(self, right_table: str, on: str, alias_left: str, alias_right: str) -> 'AsterixQueryBuilder':
        """
        Add a JOIN clause to the query.
        """
        self.current_alias = alias_left  # Set the current alias to the left table alias
        self.joins.append({
            "right_table": right_table,
            "on": on,
            "alias_left": alias_left,
            "alias_right": alias_right
        })
        return self
 
    def _build_join_clause(self) -> str:
        """Build the JOIN clause."""
        if not self.joins:
            return ""
        join_clauses = []
        for join in self.joins:
            right_table = join["right_table"].split(".")[-1]  # Remove dataverse prefix
            join_clauses.append(
                f"JOIN {right_table} {join['alias_right']} "
                f"ON {join['alias_left']}.{join['on']} = {join['alias_right']}.{join['on']}"
            )
        return " ".join(join_clauses)

    def build(self) -> str:
        """Build the complete SQL++ query string."""
        if not self.from_dataset:
            raise ValueError("No dataset specified")

        query_parts = []

        # Add USE statement if dataverse is specified
        if self.current_dataverse:
            query_parts.append(f"USE {self.current_dataverse};")

        # Build SELECT clause
        query_parts.append(self._build_select_clause())

        # Build FROM clause with JOINs if present
        # Use the join's left alias if available, otherwise use default alias
        table_alias = self.joins[0]['alias_left'] if self.joins else 'b' if 'Businesses' in self.from_dataset else 'r'
        from_clause = f"FROM {self.from_dataset} {table_alias}"
        
        if self.joins:
            join_clauses = []
            for join in self.joins:
                right_table = join['right_table'].split('.')[-1]
                join_clause = (
                    f"JOIN {right_table} {join['alias_right']} "
                    f"ON {join['alias_left']}.{join['on']} = {join['alias_right']}.{join['on']}"
                )
                join_clauses.append(join_clause)
            from_clause += " " + " ".join(join_clauses)
        query_parts.append(from_clause)

        # Add UNNEST clauses after FROM
        unnest_clause = self._build_unnest_clause()
        if unnest_clause:
            query_parts.append(unnest_clause)

        # Build WHERE clause
        where_clause = self._build_where_clause()
        if where_clause:
            query_parts.append(f"WHERE {where_clause}")

        # Build GROUP BY clause
        group_by_clause = self._build_group_by_clause()
        if group_by_clause:
            query_parts.append(group_by_clause)

        # Build ORDER BY clause
        order_by_clause = self._build_order_by_clause()
        if order_by_clause:
            query_parts.append(order_by_clause)

        # Add LIMIT and OFFSET
        if self.limit_val is not None:
            query_parts.append(f"LIMIT {self.limit_val}")
        if self.offset_val is not None:
            query_parts.append(f"OFFSET {self.offset_val}")

        query = " ".join(query_parts)
        if not query.endswith(';'):
            query += ';'

        return query



