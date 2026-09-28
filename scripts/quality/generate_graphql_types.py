"""Generate strict TypeScript GraphQL operation types from SDL and documents."""

from __future__ import annotations

import argparse
from pathlib import Path

from graphql import build_ast_schema, parse, print_ast, validate
from graphql.language import ast
from graphql.type import (
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLType,
    get_named_type,
)

SCALARS = {"UUID": "string", "String": "string", "Int": "number", "Boolean": "boolean"}


def _ts_type(type_node: ast.TypeNode, schema: GraphQLSchema) -> str:
    if isinstance(type_node, ast.NonNullTypeNode):
        return _ts_type(type_node.type, schema)
    if isinstance(type_node, ast.ListTypeNode):
        value = _ts_type(type_node.type, schema)
        return f"Array<{value}> | null"
    assert isinstance(type_node, ast.NamedTypeNode)
    named = get_named_type(schema.get_type(type_node.name.value))
    return SCALARS.get(named.name, named.name) if named else "unknown"


def _schema_type(name: str, schema: GraphQLSchema) -> str:
    named = get_named_type(schema.get_type(name))
    return SCALARS.get(named.name, named.name) if named else "unknown"


def _output_type(graphql_type: GraphQLType, schema: GraphQLSchema) -> str:
    if isinstance(graphql_type, GraphQLNonNull):
        return _output_type(graphql_type.of_type, schema)
    if isinstance(graphql_type, GraphQLList):
        return f"Array<{_output_type(graphql_type.of_type, schema)}>"
    named = get_named_type(graphql_type)
    return SCALARS.get(named.name, named.name)


def generate(schema_path: Path, operations_path: Path) -> str:
    schema_document = parse(schema_path.read_text())
    schema = build_ast_schema(schema_document)
    operations_document = parse(operations_path.read_text())
    errors = validate(schema, operations_document)
    if errors:
        raise ValueError("invalid GraphQL operation: " + "; ".join(str(error) for error in errors))

    output = [
        "/** Generated from schema.graphql and operations.graphql. Do not edit by hand. */",
        "",
    ]
    output.extend(
        [
            "export type Scalars = {",
            "  UUID: string;",
            "  String: string;",
            "  Boolean: boolean;",
            "  Int: number;",
            "};",
            "",
        ]
    )
    for name in ("PublicProfile", "ViewerProfile"):
        object_type = schema.get_type(name)
        assert isinstance(object_type, GraphQLObjectType)
        output.append(f"export type {name} = {{")
        for field_name, field_def in object_type.fields.items():
            ts_name = field_name
            ts_type = _output_type(field_def.type, schema)
            if not str(field_def.type).endswith("!"):
                ts_type += " | null"
            output.append(f"  {ts_name}: {ts_type};")
        output.extend(["};", ""])

    for definition in operations_document.definitions:
        if not isinstance(definition, ast.OperationDefinitionNode):
            continue
        operation_name = next(
            (definition.name.value for definition in [definition] if definition.name), "Anonymous"
        )
        result_name = f"{operation_name}Query"
        variables_name = f"{result_name}Variables"
        output.append(f"export type {variables_name} = {{")
        for variable in definition.variable_definitions or ():
            variable_name = variable.variable.name.value
            output.append(
                f"  {variable_name}: {_ts_type(variable.type, schema).replace(' | null', '')};"
            )
        output.extend(["};", ""])
        output.append(f"export type {result_name} = {{")
        root = schema.query_type
        assert root is not None
        for field in definition.selection_set.selections:
            if not isinstance(field, ast.FieldNode):
                continue
            field_def = root.fields[field.name.value]
            ts_type = _output_type(field_def.type, schema)
            if not str(field_def.type).endswith("!"):
                ts_type += " | null"
            output.append(f"  {field.alias.value if field.alias else field.name.value}: {ts_type};")
        output.extend(["};", ""])
        constant_name = "_".join(
            part.upper() for part in __import__("re").findall(r"[A-Z][a-z]*|[a-z]+", operation_name)
        )
        output.append(f"export const {constant_name}_QUERY = `{print_ast(definition)}` as const;")
        output.append("")
    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--operations", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.schema, args.operations), end="")


if __name__ == "__main__":
    main()
