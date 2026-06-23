from app.templates.rendering import render


def test_substitutes_known_variables():
    assert render("Hi {{first_name}}!", {"first_name": "Jane"}) == "Hi Jane!"


def test_substitutes_multiple_variables():
    result = render("{{greeting}} {{first_name}}, code: {{otp}}", {"greeting": "Hi", "first_name": "Jane", "otp": "1234"})
    assert result == "Hi Jane, code: 1234"


def test_leaves_unknown_placeholder_unsubstituted():
    assert render("Hi {{first_name}}, {{missing}}!", {"first_name": "Jane"}) == "Hi Jane, {{missing}}!"


def test_non_string_variable_values_are_stringified():
    assert render("Count: {{count}}", {"count": 5}) == "Count: 5"


def test_no_placeholders_returns_text_unchanged():
    assert render("Hello world", {"unused": "value"}) == "Hello world"


def test_tolerates_whitespace_inside_braces():
    assert render("Hi {{ first_name }}!", {"first_name": "Jane"}) == "Hi Jane!"
