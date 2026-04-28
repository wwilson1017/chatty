"""Tests for the Telegram Markdown-to-HTML converter."""

from integrations.telegram.format import markdown_to_telegram_html


class TestHtmlEscaping:
    def test_ampersand(self):
        assert markdown_to_telegram_html("a & b") == "a &amp; b"

    def test_angle_brackets(self):
        assert markdown_to_telegram_html("a < b > c") == "a &lt; b &gt; c"

    def test_script_tag(self):
        assert markdown_to_telegram_html("<script>alert('x')</script>") == "&lt;script&gt;alert('x')&lt;/script&gt;"

    def test_empty_string(self):
        assert markdown_to_telegram_html("") == ""


class TestBoldItalic:
    def test_bold_double_asterisk(self):
        assert markdown_to_telegram_html("**bold**") == "<b>bold</b>"

    def test_bold_double_underscore(self):
        assert markdown_to_telegram_html("__bold__") == "<b>bold</b>"

    def test_italic_single_asterisk(self):
        assert markdown_to_telegram_html("*italic*") == "<i>italic</i>"

    def test_bold_and_italic(self):
        result = markdown_to_telegram_html("**bold** and *italic*")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result

    def test_strikethrough(self):
        assert markdown_to_telegram_html("~~struck~~") == "<s>struck</s>"


class TestCode:
    def test_inline_code(self):
        assert markdown_to_telegram_html("`some code`") == "<code>some code</code>"

    def test_inline_code_html_escaped(self):
        assert markdown_to_telegram_html("`a < b`") == "<code>a &lt; b</code>"

    def test_fenced_code_block(self):
        text = "```python\nprint('hello')\n```"
        result = markdown_to_telegram_html(text)
        assert '<pre><code class="language-python">' in result
        assert "print('hello')" in result
        assert "</code></pre>" in result

    def test_fenced_code_no_language(self):
        text = "```\nsome code\n```"
        result = markdown_to_telegram_html(text)
        assert "<pre><code>" in result
        assert "some code" in result

    def test_code_block_preserves_content(self):
        text = "```\n**not bold** & <not tag>\n```"
        result = markdown_to_telegram_html(text)
        assert "**not bold**" in result
        assert "&amp;" in result
        assert "&lt;not tag&gt;" in result
        assert "<b>" not in result


class TestLinks:
    def test_basic_link(self):
        result = markdown_to_telegram_html("[click](https://example.com)")
        assert result == '<a href="https://example.com">click</a>'

    def test_link_with_special_chars_in_url(self):
        result = markdown_to_telegram_html("[x](https://a.com/?q=1&r=2)")
        assert 'href="https://a.com/?q=1&amp;r=2"' in result


class TestBlockElements:
    def test_header_h1(self):
        assert markdown_to_telegram_html("# Title") == "<b>Title</b>"

    def test_header_h3(self):
        assert markdown_to_telegram_html("### Sub") == "<b>Sub</b>"

    def test_blockquote_single_line(self):
        result = markdown_to_telegram_html("> quoted text")
        assert "<blockquote>" in result
        assert "quoted text" in result

    def test_blockquote_multiline(self):
        result = markdown_to_telegram_html("> line one\n> line two")
        assert "<blockquote>" in result
        assert "line one" in result
        assert "line two" in result
        assert result.count("<blockquote>") == 1


class TestRealisticAiResponse:
    def test_mixed_response(self):
        text = (
            "Your 8:10 AM skin check on May 22 is already on the family calendar:\n\n"
            "* **Will skin check** — Nashville Skin — Jessica Swindell\n"
            "* **May 22 (Friday)** at 8:10 AM\n"
            "* **No conflicts** — first work meeting isn't until 10 AM\n\n"
            "You're good to go."
        )
        result = markdown_to_telegram_html(text)
        assert "<b>Will skin check</b>" in result
        assert "<b>May 22 (Friday)</b>" in result
        assert "<b>No conflicts</b>" in result
        assert "You're good to go." in result
        assert "**" not in result
