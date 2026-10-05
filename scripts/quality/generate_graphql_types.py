"""Generate strict TypeScript GraphQL operation types from SDL and documents."""

from __future__ import annotations

import argparse
from pathlib import Path

from graphql import build_ast_schema, parse, print_ast, validate
from graphql.language import ast
from graphql.type import (
    GraphQLEnumType,
    GraphQLNamedType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLType,
    get_named_type,
)

SCALARS = {
    "Boolean": "boolean",
    "DateTime": "string",
    "Int": "number",
    "String": "string",
    "UUID": "string",
}


def _ts_type(type_node: ast.TypeNode, schema: GraphQLSchema) -> str:
    if isinstance(type_node, ast.NonNullTypeNode):
        return _ts_type(type_node.type, schema).removesuffix(" | null")
    if isinstance(type_node, ast.ListTypeNode):
        value = _ts_type(type_node.type, schema)
        return f"Array<{value}> | null"
    assert isinstance(type_node, ast.NamedTypeNode)
    named = get_named_type(schema.get_type(type_node.name.value))
    return f"{_named_ts_type(named) if named else 'unknown'} | null"


def _schema_type(name: str, schema: GraphQLSchema) -> str:
    named = get_named_type(schema.get_type(name))
    return _named_ts_type(named) if named else "unknown"


def _named_ts_type(named: GraphQLNamedType) -> str:
    if isinstance(named, GraphQLEnumType):
        return " | ".join(f'"{value}"' for value in named.values)
    return SCALARS.get(named.name, named.name)


def _output_type(
    graphql_type: GraphQLType,
    schema: GraphQLSchema,
    selection_set: ast.SelectionSetNode | None = None,
    *,
    nullable: bool = True,
) -> str:
    if isinstance(graphql_type, GraphQLNonNull):
        return _output_type(graphql_type.of_type, schema, selection_set, nullable=False)
    if isinstance(graphql_type, GraphQLList):
        output_type = f"Array<{_output_type(graphql_type.of_type, schema, selection_set)}>"
    else:
        named = get_named_type(graphql_type)
        scalar_type = SCALARS.get(named.name)
        if scalar_type is not None:
            output_type = scalar_type
        elif isinstance(named, GraphQLEnumType):
            output_type = _named_ts_type(named)
        elif isinstance(named, GraphQLObjectType):
            if selection_set is None:
                raise ValueError(f"object field {named.name} requires a selection set")
            output_type = _selection_type(selection_set, named, schema)
        else:
            output_type = "unknown"
    return f"{output_type} | null" if nullable else output_type


def _selection_type(
    selection_set: ast.SelectionSetNode, parent: GraphQLObjectType, schema: GraphQLSchema
) -> str:
    fields = ["{"]
    for selection in selection_set.selections:
        if not isinstance(selection, ast.FieldNode):
            raise ValueError("GraphQL fragments are not supported in generated operations")
        name = selection.name.value
        field_def = parent.fields[name]
        output_type = _output_type(field_def.type, schema, selection.selection_set)
        fields.append(f"    {selection.alias.value if selection.alias else name}: {output_type};")
    fields.append("  }")
    return "\n".join(fields)


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
            ts_type = _output_type(field_def.type, schema)
            output.append(f"  {field_name}: {ts_type};")
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
            required = (
                isinstance(variable.type, ast.NonNullTypeNode) and variable.default_value is None
            )
            variable_type = _ts_type(variable.type, schema)
            if required:
                variable_type = variable_type.replace(" | null", "")
            output.append(f"  {variable_name}{'' if required else '?'}: {variable_type};")
        output.extend(["};", ""])
        output.append(f"export type {result_name} = {{")
        root = schema.query_type
        assert root is not None
        for field in definition.selection_set.selections:
            if not isinstance(field, ast.FieldNode):
                continue
            field_def = root.fields[field.name.value]
            ts_type = _output_type(field_def.type, schema, field.selection_set)
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
