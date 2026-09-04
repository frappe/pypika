"""An identifier must not be able to break out of its quotes.

Callers routinely build columns from request data -- ``table[request_filter_key]`` -- so a name
carrying the quote char used to close the identifier early, leaving the rest to be parsed as SQL:

    >>> Query.from_(users).select(users["name`=1 UNION SELECT secret FROM `admins` -- "])
    SELECT `name`=1 UNION SELECT secret FROM `admins` -- ` FROM `users`
"""

import unittest

from pypika import MySQLQuery, Query, Schema, Table, Tables
from pypika.terms import Field

__author__ = "Diptanil Saha"
__email__ = "diptanil.dev@gmail.com"


INJECTIONS = (
    "` blah`",
    "name`=1 UNION SELECT (SELECT api_secret FROM `tabUser` LIMIT 1),2 -- ",
    "name` FROM `tabUser`-- ",
    "account`=(SELECT api_secret FROM `tabUser` LIMIT 1) OR `account",
    "name`=1-- ",
    'name"=1-- ',
    "name);DROP TABLE users;--",
)


class ColumnNameInjectionTests(unittest.TestCase):
    table = Table("abc")

    def assertNoBreakout(self, sql: str, name: str, quote_char: str) -> None:
        """Every quote char in the name is doubled, so none of them ends the identifier."""
        q = quote_char
        self.assertEqual(f"SELECT {q}{name.replace(q, q * 2)}{q} FROM {q}abc{q}", sql)

    def test_subscript_cannot_break_out(self):
        for name in INJECTIONS:
            with self.subTest(name=name):
                self.assertNoBreakout(MySQLQuery.from_(self.table).select(self.table[name]).get_sql(), name, "`")
                self.assertNoBreakout(Query.from_(self.table).select(self.table[name]).get_sql(), name, '"')

    def test_getattr_cannot_break_out(self):
        for name in INJECTIONS:
            with self.subTest(name=name):
                sql = MySQLQuery.from_(self.table).select(getattr(self.table, name)).get_sql()
                self.assertNoBreakout(sql, name, "`")

    def test_field_method_cannot_break_out(self):
        for name in INJECTIONS:
            with self.subTest(name=name):
                sql = MySQLQuery.from_(self.table).select(self.table.field(name)).get_sql()
                self.assertNoBreakout(sql, name, "`")

    def test_field_constructor_cannot_break_out(self):
        for name in INJECTIONS:
            with self.subTest(name=name):
                self.assertNoBreakout(MySQLQuery.from_(self.table).select(Field(name)).get_sql(), name, "`")

    def test_backtick_is_doubled(self):
        payload = "name`=1 UNION SELECT api_secret FROM `tabUser` -- "
        self.assertEqual(
            "SELECT `name``=1 UNION SELECT api_secret FROM ``tabUser`` -- ` FROM `abc`",
            MySQLQuery.from_(self.table).select(self.table[payload]).get_sql(),
        )

    def test_double_quote_is_doubled(self):
        self.assertEqual(
            'SELECT "na""me" FROM "abc"',
            Query.from_(self.table).select(self.table['na"me']).get_sql(),
        )


class OtherIdentifierInjectionTests(unittest.TestCase):
    """Table names, schemas and aliases quote the same way as columns."""

    def test_table_name_is_escaped(self):
        self.assertEqual('SELECT * FROM "ab""c"', Query.from_(Table('ab"c')).select("*").get_sql())

    def test_schema_name_is_escaped(self):
        table = Table("abc", schema=Schema('sch"ema'))
        self.assertEqual('SELECT * FROM "sch""ema"."abc"', Query.from_(table).select("*").get_sql())

    def test_alias_is_escaped(self):
        table = Table("abc")
        self.assertEqual(
            'SELECT "foo" "a""lias" FROM "abc"',
            Query.from_(table).select(table.foo.as_('a"lias')).get_sql(),
        )


class NoRegressionTests(unittest.TestCase):
    """Escaping must not disturb anything that was already correct."""

    table = Table("abc")

    def test_plain_names_are_unchanged(self):
        self.assertEqual(
            'SELECT "foo","_assign","café_naïve" FROM "abc"',
            Query.from_(self.table).select(self.table.foo, self.table["_assign"], self.table["café_naïve"]).get_sql(),
        )

    def test_star_is_unchanged(self):
        self.assertEqual('SELECT * FROM "abc"', Query.from_(self.table).select(self.table.star).get_sql())
        self.assertEqual('SELECT * FROM "abc"', Query.from_(self.table).select("*").get_sql())

    def test_dotted_select_str_is_unchanged(self):
        # pre-existing behaviour: a column literally named "a.*"
        self.assertEqual('SELECT "a.*" FROM "abc"', Query.from_(self.table).select("a.*").get_sql())

    def test_string_values_are_still_escaped_once(self):
        # value escaping moved out of `ValueWrapper`; a quote must still be doubled once, not twice
        self.assertEqual(
            "SELECT \"foo\" FROM \"abc\" WHERE \"foo\"='it''s'",
            Query.from_(self.table).select(self.table.foo).where(self.table.foo == "it's").get_sql(),
        )

    def test_value_cannot_break_out_of_string_literal(self):
        payload = "x' OR 1=1 -- "
        sql = Query.from_(self.table).select(self.table.foo).where(self.table.foo == payload).get_sql()
        self.assertEqual("SELECT \"foo\" FROM \"abc\" WHERE \"foo\"='x'' OR 1=1 -- '", sql)


class JoinedTableInjectionTests(unittest.TestCase):
    def test_namespaced_field_cannot_break_out(self):
        a, b = Tables("a", "b")
        payload = "id` FROM `secrets` -- "
        sql = MySQLQuery.from_(a).join(b).on(a.id == b.a_id).select(b[payload]).get_sql()
        self.assertIn("`b`.`id`` FROM ``secrets`` -- `", sql)
