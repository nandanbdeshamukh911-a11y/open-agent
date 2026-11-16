import ast
import json
import operator
import re
from decimal import Decimal, DecimalException, localcontext


CATALOG = [
    {'id': 'calculate', 'name': 'Calculator', 'description': 'Evaluate arithmetic with up to 34 significant digits.', 'placeholder': '(19.95 * 3) + 4.50'},
    {'id': 'json', 'name': 'Format JSON', 'description': 'Validate and indent JSON without changing numeric values.', 'placeholder': '{"name":"Open Agent","local":true}'},
    {'id': 'text_stats', 'name': 'Text statistics', 'description': 'Count words, Unicode characters, and lines.', 'placeholder': 'Paste text to count…'},
]

OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow,
}


def calculate(text):
    if len(text) > 500:
        raise ValueError('Enter a shorter arithmetic expression.')
    expression = text.strip()
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise ValueError('Enter a valid arithmetic expression.') from exc

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(expression, node)
            if literal and re.fullmatch(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', literal):
                return Decimal(literal)
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            operand = evaluate(node.operand)
            return -operand if isinstance(node.op, ast.USub) else operand
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and (right != right.to_integral_value() or abs(right) > 100):
                raise ValueError('Use an integer exponent from −100 to 100.')
            return OPERATORS[type(node.op)](left, right)
        raise ValueError('Use decimal numbers, parentheses, and +, -, *, /, or **.')

    try:
        with localcontext() as context:
            context.prec = 34
            context.Emax = 999
            context.Emin = -999
            result = +evaluate(tree.body)
            return str(result.normalize()) if result.adjusted() >= 34 or result.adjusted() < -12 else format(result.normalize(), 'f')
    except (DecimalException, RecursionError) as exc:
        raise ValueError('The calculation is undefined or exceeds the supported range.') from exc


def format_json(text):
    def reject_constant(value):
        raise ValueError(f'{value} is outside the JSON standard.')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    try:
        json.loads(text, parse_int=str, parse_float=str, parse_constant=reject_constant, object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}') from exc
    except RecursionError as exc:
        raise ValueError('The JSON is nested too deeply.') from exc

    # Format the validated tokens directly, preserving numbers and string escapes.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:]+', text)
    output, depth = [], 0
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else ''
        following = tokens[index + 1] if index + 1 < len(tokens) else ''
        if token in ('{', '['):
            output.append(token)
            depth += 1
            if following not in ('}', ']'):
                output.append('\n' + '  ' * depth)
        elif token in ('}', ']'):
            depth -= 1
            if previous not in ('{', '['):
                output.append('\n' + '  ' * depth)
            output.append(token)
        elif token == ',':
            output.append(',\n' + '  ' * depth)
        else:
            output.append(': ' if token == ':' else token)
    result = ''.join(output)
    if len(result) > 120000:
        raise ValueError('Formatted JSON exceeds the output limit.')
    return result


def text_stats(text):
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text)
    return f'Words: {len(words):,}\nCharacters: {len(text):,}\nLines: {len(text.splitlines()):,}'


TOOLS = {'calculate': calculate, 'json': format_json, 'text_stats': text_stats}
