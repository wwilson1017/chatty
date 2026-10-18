"""The gate classifier (PR 3): the plan's adversarial fixtures, expressed as the element
descriptions the computer's /browser/element returns, plus the four-step checkout."""

import pytest

from integrations.computer import gates
from integrations.computer.gates import classify, needs_check


def el(name="", *, tag="button", role="button", type=None, is_submit=False, form=None, host="shop.example",
       path="/product/42", title="Shop", frame_url=None, context_kind=None, found=True):
    """A /browser/element description. `form` is the computer's form object (action, method, and
    PR 1's role/text/fields when present); giving it puts the element inside a form."""
    return {
        "found": found, "ref": "e10", "tag": tag, "role": role, "name": name, "type": type, "href": None,
        "is_submit": is_submit, "form": form, "frame_url": frame_url or f"https://{host}{path}",
        "page": {"host": host, "path": path, "title": title},
        "context_kind": context_kind or ("form" if form else None), "context_fp": "fp" if form else None,
        "total": None,
    }


def form(method="post", action="https://shop.example/submit", role=None, text=None, fields=None):
    f = {"action": action, "method": method}
    if role is not None:
        f["role"] = role
    if text is not None:
        f["text"] = text
    if fields is not None:
        f["fields"] = fields
    return f


def field(type="text", name="f", autocomplete=None, visible=True):
    return {"name": name, "type": type, "autocomplete": autocomplete, "visible": visible}


PAYMENT_PAGE = '- heading "Payment" [level=1]\n- textbox "Card number" [ref=e3]\n- textbox "CVC" [ref=e4]\n- button "Continue" [ref=e10]'
SHIPPING_PAGE = '- heading "Shipping address" [level=1]\n- textbox "Street" [ref=e3]\n- button "Continue" [ref=e10]'


class TestWhatIsChecked:
    @pytest.mark.parametrize("label", ["left_click", "right_click", "middle_click", "double_click", "triple_click",
                                       "left_mouse_down", "left_click_drag", "act:click", "act:select",
                                       "key:Return", "key:KP_Enter", "key:space", "key:ctrl+Return", "key:cmd+s",
                                       "hold_key:Return", "act:press:Enter", "act:press:Space", "act:press:Control+Enter"])
    def test_checked(self, label):
        assert needs_check(label)

    @pytest.mark.parametrize("label", ["screenshot", "zoom", "mouse_move", "scroll", "wait", "cursor_position",
                                       "left_mouse_up", "key:Tab", "key:ArrowDown", "key:ctrl+a", "act:fill",
                                       "act:hover", "act:scroll", "act:navigate", "act:back", "act:press:Tab"])
    def test_free(self, label):
        assert not needs_check(label)

    def test_type_only_with_newline(self):
        assert needs_check("type", "hello\n") and needs_check("act:type", "a\nb")
        assert needs_check("act:type", "a\rb") and needs_check("type", "a b")  # every newline Playwright types as Enter
        assert not needs_check("type", "hello") and not needs_check("act:type", "")

    @pytest.mark.parametrize("label", ["act:press:NumpadEnter", "key:KP_Enter", "act:press:ControlOrMeta+Enter",
                                       "act:press:Shift+Enter", "act:press:Space", "act:press: ", "act:press:",
                                       "act:press:SomethingNew", "act:press:ContextMenu"])
    def test_enter_aliases_and_unknown_keys_are_checked(self, label):
        assert needs_check(label)

    def test_unknown_keys_fail_closed_as_enter_and_free_keys_stay_free(self):
        target = el("Email", tag="input", role="textbox", type="email", form=form())
        assert classify("act:press:NumpadEnter", target).gated
        assert classify("act:press:SomethingNew", target).rule == "6.form"
        assert classify("act:press:ControlOrMeta+Enter", None).kind == "send"
        assert classify("act:press:ControlOrMeta+s", target).rule == "5.confirm"
        for label in ("act:press:ArrowDown", "act:press:Shift+Tab", "act:press:KeyA", "act:press:a", "act:press:Alt+ArrowLeft",
                      "act:press:Control+a", "act:press:F5", "act:press:Digit1", "key:ctrl+c", "act:press:Escape"):
            assert not needs_check(label) or not classify(label, el("Place order")).gated, label


class TestAdversarialFixtures:
    def test_js_confirm_button_that_orders(self):
        v = classify("act:click", el("Confirm"))
        assert v.gated and v.kind == "submit" and v.rule == "5.confirm"

    def test_purchase_on_pointerdown_is_gated_at_press(self):
        v = classify("left_mouse_down", el("Buy now"))
        assert v.gated and v.kind == "buy" and v.rule == "1.buy"
        assert classify("left_click_drag", el("Buy now")).gated

    def test_yes_dialog(self):
        v = classify("left_click", el("Yes", role="button"))
        assert v.gated and v.kind == "submit"

    def test_enter_in_one_field_form_and_repeated_enter(self):
        target = el("Email", tag="input", role="textbox", type="email", form=form(), path="/newsletter")
        v = classify("act:press:Enter", target)
        assert v.gated and v.kind == "submit" and v.rule == "6.form" and not v.multi
        assert classify("key:Return", target, repeat=3).multi
        assert classify("hold_key:Return", target).multi
        assert classify("type", target).gated  # typed text with a newline is Enter

    def test_space_on_focused_button_but_not_in_a_text_field(self):
        assert classify("act:press:Space", el("Yes")).gated
        assert classify("key:space", el("Pay", role="button")).kind == "buy"
        assert not classify("key:space", el("Message", tag="textarea", role="textbox")).gated
        assert not classify("act:press:Space", el("Search", tag="input", role="textbox", type="text")).gated

    def test_ctrl_enter_composer_is_send_anywhere(self):
        for label in ("act:press:Control+Enter", "key:ctrl+Return", "key:cmd+Return", "act:press:Meta+Enter"):
            v = classify(label, el("Message", tag="div", role="textbox"))
            assert v.gated and v.kind == "send", label
        assert classify("key:ctrl+Return", None).kind == "send"  # no element needed

    def test_ctrl_s_saves(self):
        assert classify("key:ctrl+s", el("Doc", tag="div", role="textbox")).kind == "submit"

    def test_checkout_page_unlabeled_icon_button(self):
        v = classify("act:click", el("", role="button", path="/checkout"))
        assert v.gated and v.kind == "buy" and v.rule == "4.checkout"
        # ... and a checkout page recognised by title alone
        assert classify("act:click", el("", role="button", path="/step2", title="Your Order")).rule == "4.checkout"

    def test_signup_form_with_one_password_and_no_autocomplete_is_gated(self):
        f = form(text="create your account email password continue",
                 fields=[field("email", "email"), field("password", "password")])
        v = classify("act:click", el("Continue", is_submit=True, form=f, path="/signup"))
        assert v.gated and v.kind == "submit" and v.rule == "6.form"
        f2 = form(text="sign up email password sign up", fields=[field("email", "email"), field("password", "password")])
        assert classify("act:click", el("Sign up", is_submit=True, form=f2, path="/signup")).gated

    def test_account_settings_update_is_gated(self):
        f = form(text="your details name email update", fields=[field("text", "name"), field("email", "email")])
        v = classify("act:click", el("Update", is_submit=True, form=f, path="/account"))
        assert v.gated and v.kind == "submit" and v.rule == "5.confirm"

    def test_real_login_form_is_free(self):
        f = form(text="sign in to your account email password forgot password? sign in",
                 fields=[field("email", "email"), field("password", "password", autocomplete="current-password")])
        target = el("Sign in", is_submit=True, form=f, path="/login")
        assert classify("act:click", target).rule == "2.login"
        assert classify("act:press:Enter", el("Password", tag="input", role="textbox", type="password", form=f, path="/login")).rule == "2.login"

    def test_login_lookalikes_stay_gated(self):
        pw = field("password", "password")
        # a sign-up link on the form itself → ambiguous → gated
        assert classify("act:click", el("Sign in", is_submit=True, path="/login", form=form(
            text="sign in email password sign in or create an account", fields=[field("email", "email"), pw]))).gated
        # new-password autocomplete
        assert classify("act:click", el("Sign in", is_submit=True, path="/login", form=form(
            text="sign in", fields=[field("email", "email"), field("password", "password", autocomplete="new-password")]))).gated
        # two password fields
        assert classify("act:click", el("Continue", is_submit=True, path="/login", form=form(
            text="continue", fields=[field("email", "email"), pw, field("password", "confirm")]))).gated
        # too many other fields
        assert classify("act:click", el("Sign in", is_submit=True, path="/login", form=form(
            text="sign in", fields=[field("text", "first"), field("text", "last"), field("email", "email"), pw]))).gated
        # the computer didn't describe the fields (older PR 1 build): can't be positively identified
        assert classify("act:click", el("Sign in", is_submit=True, path="/login", form=form())).gated

    def test_get_search_form_is_free(self):
        f = form(method="get", action="https://shop.example/search", role="search")
        assert classify("act:click", el("Search", is_submit=True, form=f)).rule == "2.search"
        f2 = form(method="get", action="https://shop.example/search", fields=[field("search", "q")])
        assert classify("act:press:Enter", el("Search", tag="input", role="searchbox", type="search", form=f2)).rule == "2.search"
        # ... but not on a checkout page, and not a POST
        assert classify("act:click", el("Search", is_submit=True, form=f, path="/checkout")).gated
        assert classify("act:click", el("Search", is_submit=True, form=form(method="post", role="search"))).gated

    def test_unidentified_target_fails_closed(self):
        v = classify("act:click", {"found": False, "page": {"host": "x", "path": "/", "title": ""}})
        assert v.gated and v.rule == "unidentified"
        assert classify("left_click", None).gated


class TestFourStepCheckout:
    """Real submitting forms: cart → shipping → payment → review."""

    def test_cart_legwork_is_free(self):
        f = form(action="https://shop.example/cart")
        for name in ("Update quantity", "Apply coupon", "Remove item"):
            assert classify("act:click", el(name, is_submit=True, form=f, path="/cart", title="Cart")).rule == "2.cart", name

    def test_shipping_continue_is_free(self):
        f = form(action="https://shop.example/checkout/shipping")
        v = classify("act:click", el("Continue", is_submit=True, form=f, path="/checkout/shipping"), page_text=SHIPPING_PAGE)
        assert v.rule == "2.shipping" and not v.gated

    def test_payment_continue_is_a_buy_gate(self):
        f = form(action="https://shop.example/checkout/payment")
        v = classify("act:click", el("Continue", is_submit=True, form=f, path="/checkout/payment"), page_text=PAYMENT_PAGE)
        assert v.gated and v.kind == "buy"
        # the same with card fields known only from the form description
        f2 = form(fields=[field("text", "cardnumber", autocomplete="cc-number"), field("text", "cvc")])
        assert classify("act:click", el("Continue", is_submit=True, form=f2, path="/checkout/payment")).kind == "buy"

    def test_review_place_order_is_a_buy_gate(self):
        f = form(action="https://shop.example/order")
        v = classify("act:click", el("Place order", is_submit=True, form=f, path="/checkout/review"))
        assert v.gated and v.kind == "buy" and v.rule == "1.buy"


class TestLegworkAndKinds:
    def test_non_submitting_legwork_is_free(self):
        for name in ("Add to cart", "Quantity", "Remove item", "Continue shopping", "Back", "Edit", "Change", "Filter", "Next page", "Next", "Continue"):
            assert not classify("act:click", el(name)).gated, name

    def test_continue_with_payment_form_showing_is_a_buy_gate_even_off_checkout(self):
        v = classify("act:click", el("Continue", path="/give"), page_text=PAYMENT_PAGE)
        assert v.gated and v.kind == "buy" and v.rule == "3.continue-payment"

    def test_kind_words(self):
        assert classify("act:click", el("Share", role="link")).kind == "post"
        assert classify("act:click", el("Delete")).kind == "delete"
        assert classify("act:click", el("Send")).kind == "send"
        assert classify("act:click", el("Reply all")).kind == "send"
        assert classify("act:click", el("Reply")).kind == "post"
        assert classify("act:click", el("Cancel subscription")).kind == "delete"
        assert classify("act:click", el("Donate")).kind == "buy"
        assert classify("act:click", el("Subscribe")).kind == "buy"
        assert not classify("act:click", el("Postal code", tag="input", role="textbox", type="text")).gated
        assert not classify("act:click", el("PayPal FAQ", role="link")).gated

    def test_sign_in_link_is_navigation_but_sign_is_a_confirmation(self):
        assert not classify("act:click", el("Sign in", role="link")).gated
        assert not classify("act:click", el("Sign out", role="link")).gated
        assert classify("act:click", el("Sign")).rule == "5.confirm"

    def test_composer_enter_outside_a_form_is_send(self):
        v = classify("act:press:Enter", el("Message", tag="div", role="textbox"))
        assert v.gated and v.kind == "send" and v.rule == "7.composer"
        assert classify("act:type", el("Message", tag="textarea", role="textbox")).kind == "send"
        # inside a form Enter in a textarea is a newline (the plan's rule 7 is outside-form only)
        assert not classify("act:press:Enter", el("Notes", tag="textarea", role="textbox", form=form())).gated

    def test_checkout_page_keeps_checkboxes_and_selects_free(self):
        assert not classify("act:click", el("Gift wrap", tag="input", role="checkbox", type="checkbox", path="/checkout")).gated
        assert not classify("act:select", el("Country", tag="select", role="combobox", path="/checkout")).gated

    def test_double_click_on_a_gated_target_is_multi(self):
        v = classify("double_click", el("Buy"))
        assert v.gated and v.multi
        assert not classify("double_click", el("Title", tag="h1", role="heading")).gated


def test_expect_for_carries_the_seven_required_fields():
    e = el("Continue", is_submit=True, form=form(action="https://shop.example/ship"), path="/checkout/shipping")
    x = gates.expect_for("act:click", e)
    assert x == {"action": "act:click", "host": "shop.example", "path": "/checkout/shipping",
                 "frame_url": "https://shop.example/checkout/shipping", "role": "button", "name": "Continue",
                 "form_action": "https://shop.example/ship"}
    assert "context_fp" not in x and "total" not in x
