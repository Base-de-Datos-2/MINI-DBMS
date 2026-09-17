# Stage 7 SQL grammar and execution contract

**Frozen:** 2026-09-17 for Tasks 7.2-7.7. This is an implementation contract,
not an additional academic requirement. The lexer and parser are handwritten;
the parser uses recursive descent and does not depend on Lark.

## Source and token conventions

- A source span uses a zero-based inclusive `start` offset and exclusive `end`
  offset. Display lines and columns are one-based and also use an exclusive end.
- Every token stores its exact `lexeme`, a normalized parser-facing `value`, a
  typed `decoded` value when meaningful, and its `SourceSpan`.
- Comparison operators, punctuation, plus, and minus have distinct token kinds.
- Keywords are recognized only after scanning a complete identifier and are
  compared case-insensitively. Identifier spelling is preserved and Catalog
  lookup remains case-sensitive.
- Supported keywords and recognized unsupported SQL reserved words are tokens,
  so words such as `LEFT`, `DISTINCT`, `NULL`, `RETURNING`, and transaction/DDL
  verbs cannot be misread as implicit aliases. Aggregate names remain ordinary
  identifiers and become calls only when followed by `(` in a SELECT item.
- `!=` and `<>` are both accepted and normalized to `<>`. `+` and `-` are
  separate token kinds; the parser may attach one sign only to a numeric
  literal. General arithmetic expressions are outside the Stage 7 contract.
- One `EOF` token is emitted after the entire input. Semicolons do not stop the
  lexer, which lets the parser reject a second statement.
- SQL input is limited to 65,536 Python characters. A numeric literal is
  limited to 1,024 digits; decimal values must decode to a finite Python float.
  The binder must still check the target `DataType` range.
- Whitespace and `--` line comments are discarded outside strings. Block
  comments and quoted identifiers are rejected. Text resembling a comment
  inside a string remains string content.
- Strings use single quotes and decode doubled single quotes. Integer syntax is
  ASCII digits only before an optional parser-attached sign. Decimal syntax requires
  digits on both sides of the decimal point. Exponents, `NaN`, and infinity are
  not literals in this grammar.

## Grammar

The notation is EBNF. Brackets mean optional content, braces mean repetition,
and keyword spelling is case-insensitive.

```ebnf
statement       = (select_stmt | insert_stmt | delete_stmt), [";"], EOF ;

select_stmt     = "SELECT", select_list, "FROM", table_ref,
                  [join_clause], [where_clause],
                  [group_by_clause], [order_by_clause] ;
select_list     = "*" | select_item, {",", select_item} ;
select_item     = select_expr, [alias] ;
select_expr     = aggregate_call | column_ref | qualified_star ;
alias           = ["AS"], identifier ;

table_ref       = identifier, [alias] ;
join_clause     = ["INNER"], "JOIN", table_ref, "ON", bool_expr ;
where_clause    = "WHERE", bool_expr ;
group_by_clause = "GROUP", "BY", column_ref, {",", column_ref} ;
order_by_clause = "ORDER", "BY", order_item, {",", order_item} ;
order_item      = value_expr, ["ASC" | "DESC"] ;

bool_expr       = or_expr ;
or_expr         = and_expr, {"OR", and_expr} ;
and_expr        = not_expr, {"AND", not_expr} ;
not_expr        = "NOT", not_expr | "(", bool_expr, ")" | comparison ;
comparison      = value_expr, ("=" | "<>" | "!=" | "<" | "<=" | ">" | ">="),
                  value_expr ;
value_expr      = signed_number | string | "TRUE" | "FALSE" | column_ref ;
signed_number   = ["+" | "-"], (integer | decimal) ;
column_ref      = identifier, [".", identifier] ;
qualified_star  = identifier, ".", "*" ;

aggregate_call  = "COUNT", "(", ("*" | column_ref), ")"
                | ("SUM" | "AVG" | "MIN" | "MAX"), "(", column_ref, ")" ;

insert_stmt     = "INSERT", "INTO", identifier,
                  ["(", identifier, {",", identifier}, ")"],
                  "VALUES", "(", literal, {",", literal}, ")" ;
delete_stmt     = "DELETE", "FROM", identifier, [where_clause] ;
literal         = signed_number | string | "TRUE" | "FALSE" ;
```

The parser enforces `literal` for INSERT values, attaches at most one sign to a
numeric literal, and rejects arbitrary unary arithmetic.

## Adopted policy

| Topic | Decision |
|---|---|
| Submission | Exactly one complete statement; one optional final semicolon |
| Parser | Handwritten recursive descent with one-token lookahead |
| Delimiters | The enclosing production consumes commas/parentheses; the public entry consumes semicolon and EOF |
| Repetition | Loops own lists and repeated `AND`/`OR`; recursive calls own `NOT` and parentheses |
| Precedence | comparison > `NOT` > `AND` > `OR` |
| Nesting | Maximum Boolean nesting is 128 across NOT and parentheses; the parser enforces it as a controlled `SqlLimitError` |
| Aliases | Relation and output aliases accept `AS` or the unambiguous implicit form |
| Stars | `*`, `relation.*`, and `COUNT(*)` are distinct AST forms |
| Comments | `--` through end of line is accepted; block comments are rejected |
| DELETE | Whole-table `DELETE FROM table` is adopted; the executor must use the same validation and index-maintenance path as filtered DELETE |
| INSERT | One row only; an optional column list is adopted |
| JOIN | At most one explicit inner `JOIN`; its executable baseline is an equality key plus any supported residual predicate |
| Aggregates | `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, and `MAX`, subject to Stage 6 type rules |
| NULL | No SQL `NULL` literal or three-valued logic is adopted because the current row model does not support it |
| Unsupported | UPDATE, DDL, transactions, subqueries, expressions, multi-row VALUES, quoted identifiers, and multiple statements |

`DELETE` without `WHERE`, implicit aliases, qualified stars, line comments,
multiple ORDER/GROUP keys, and the optional INSERT column list are explicit
project choices. They are not claimed as academic requirements.

## Production ownership

| Grammar area | Parser method / AST result |
|---|---|
| complete statement | `parse_sql` / `SelectStatement`, `InsertStatement`, `DeleteStatement` |
| SELECT and clauses | `_parse_select`, clause helpers / `SelectItem`, `TableRef`, `JoinClause`, `OrderItem` |
| Boolean precedence | `_parse_or`, `_parse_and`, `_parse_not`, `_parse_comparison` / Boolean and comparison expressions |
| names and literals | `_parse_select_reference`, `_parse_column_ref`, `_parse_literal`, `_parse_value_expr` / unresolved references and literals |
| writes | `_parse_insert`, `_parse_delete` / write statement AST nodes |

The AST contains syntax and source locations only. It cannot contain Catalog
objects, RIDs, storage objects, physical operators, or mutation behavior.

## Feature coverage and execution route

“Planned” names the tasks that must provide semantic and physical support. It
does not claim that the current repository already implements them.

| Feature | Grammar / AST | Binder | Planner / executor | Tests |
|---|---|---|---|---|
| SELECT, projection, aliases, star | Tasks 7.3, 7.5 | implemented in 7.8, 7.10 | basic TableScan/IndexScan + final Projection implemented in 7.13-7.17; execution API 7.21 | syntax/binding/basic planning verified; end-to-end 7.27 |
| WHERE and Boolean predicates | 7.5 | implemented in 7.9 | TableScan/B+/hash candidate + complete Filter implemented in 7.14-7.17 | syntax/binding/basic planning verified; end-to-end 7.27 |
| ORDER BY | 7.5 | implemented in 7.10 | `ExternalSort`, 7.18 | binding verified; spill/restart 7.28 |
| GROUP BY and aggregates | 7.5 | implemented in 7.11 | `ExternalHashGroup`, 7.19 | binding verified; spill/restart 7.28 |
| one inner JOIN | 7.5 | implemented in 7.8-7.9 | Stage 6 join operators, 7.20 | binding verified; end-to-end 7.27 |
| INSERT | 7.6 | implemented in 7.12 | validated maintenance path, 7.23-7.25 | no-write binding verified; execution pending |
| filtered/whole-table DELETE | 7.6 | implemented in 7.12 | stable targets + index maintenance, 7.24-7.25 | no-write binding verified; execution pending |
| signed numbers | lexer 7.4; parser 7.5 | target range implemented in 7.9/7.12 | existing typed expressions/mutations | syntax and semantic ranges verified |

## Semantic binding policy

`QueryEnvironment` pairs exact Catalog definitions with borrowed runtime
storage/index objects; it does not own or close them. The binder resolves every
executable column through the Stage 6 `RowLayout`/`ColumnReference` contract.
Catalog names, relation aliases, output aliases, and columns remain
case-sensitive. A relation alias replaces its original table qualifier in that
query scope.

Comparisons use exact declared types with no INTEGER/FLOAT coercion. The full
Stage 6 expression is retained as the residual condition. Only equality/range
column-literal terms that are direct or under top-level AND are exposed as safe
index candidates; `<>`, OR, and NOT remain residual-only. FLOAT signed zero is
canonicalized for index probes in the same way as the hash codec.

ORDER BY resolves a bare exact output alias before a source field. Qualified
ORDER BY references use source scope. Unselected source/group keys are retained
as hidden dependencies for later planning. Positional ordering and general
ORDER BY expressions are outside the subset.

The grouped subset requires at least one aggregate. Global aggregation without
GROUP BY is adopted when every selected item is an aggregate. COUNT(*),
COUNT(column), SUM, AVG, MIN, and MAX use Stage 6 signatures and result types;
Stage 6 also remains authoritative for empty-input behavior.

INSERT requires every schema column because NULL and defaults are absent. The
optional column list may reorder values but cannot omit or repeat fields.
Binding validates exact scalar encoding, signed-int64 range, record page
capacity, index-key compatibility, registered index availability, and known
uniqueness through read-only probes. Execution must repeat mutable-state checks
through the future maintenance service immediately before writing. DELETE
binding retains the real target storage, RID requirement, affected indexes, and
RID-movement policy but does not enumerate or remove rows.

## Basic physical-planning policy

`engine.query.planner` stores immutable physical specifications rather than
mutable operator instances. A prepared SELECT creates a fresh, closed Stage 6
operator tree on every instantiation and rechecks exact Catalog, storage, and
chosen-index identities first. The current Catalog has no public table-schema
replacement operation; identity checks still reject unversioned replacement,
index removal, closure, or incompleteness before reuse.

Every single-relation basic SELECT has a TableScan fallback. A test-only
`use_indexes=False` option forces that baseline. A compatible exact equality
candidate has priority over a B+ range candidate, with exact index name as the
deterministic tie-break; this policy is not a cost estimate. Hash indexes are
never used for ranges. Missing, closed, incomplete, mismatched, or
unrepresentable indexes are not candidates.

Index conditions come only from the binder's safe top-level conjuncts. B+
lower/upper bounds are combined with their inclusive/exclusive endpoints. OR,
NOT, `<>`, and proven contradictory intervals use TableScan. Regardless of the
leaf selected, the complete bound WHERE expression remains a Filter before the
final Projection, so hidden predicate columns and duplicate row occurrences
are preserved. ORDER BY, GROUP BY, and JOIN physical planning remain assigned
to Tasks 7.18-7.20.

## Controlled diagnostics

All front-end failures derive from `SqlQueryError`, which in turn derives from
the project `ValidationError`. `SqlLexicalError`, `SqlSyntaxError`,
`SqlUnsupportedError`, and `SqlLimitError` distinguish invalid characters,
malformed supported syntax, recognized out-of-scope syntax, and bounded-input
failures. Errors retain the offending lexeme or EOF, expected category when
known, source span, one-based line/column, offset, and a bounded line excerpt.
The lexer scans the complete submission before parsing, so an invalid character
after a valid prefix or semicolon cannot be hidden.

Semantic failures use `SqlBindingError`. Located unknown-name variants also
inherit the existing `UnknownTableError` or `UnknownColumnError`, so callers can
keep their domain-level handling while receiving SQL line/column information.

Access selection must be deterministic: use Extendible Hashing only for an
eligible full-key equality predicate; use B+ for eligible equality/ranges; use
a table scan when no compatible complete index is available. Residual terms
remain filters. If multiple indexes have equal eligibility, sort candidates by
stable index metadata name before choosing. The reported plan must name the
operator and access path actually executed.

Execution will reuse the Stage 6 `ExecutionContext`, operator lifecycle,
expressions, row layouts, and physical-plan reporting. A result owns its open
resources until exhausted or explicitly closed; execution statistics are
partial while running and final only after completion/close. A plan
specification may be executed more than once only by constructing a fresh
operator tree for each run.

INSERT and DELETE must validate before mutation, update every affected index,
and compensate completed steps after an ordinary mid-operation failure. These
rules do not claim transaction isolation, WAL durability, or crash-atomic
multi-file commits; those belong to Stage 8. Clustered/sequential writes that
move RIDs require the existing rebuild/recovery contracts rather than stale RID
reuse.
