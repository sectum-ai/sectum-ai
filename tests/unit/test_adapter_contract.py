def test_a_family_whose_methods_take_no_user_does_not_claim_to_carry_one() -> None:
    # `Adapter.carries_user` defaults to True, and the runner reads it to decide
    # whether a user-level step can be JUDGED as that user. A family whose methods
    # take no `user` cannot carry one, and the default once produced twelve false
    # CRITICAL cross-user leaks on a store never asked about a user. Pin the whole
    # set rather than the three that were fixed, so a new family cannot inherit
    # the wrong answer silently.
    import inspect

    from sectum_ai.adapters import base

    for name, cls in vars(base).items():
        if not (inspect.isclass(cls) and issubclass(cls, base.Adapter) and cls is not base.Adapter):
            continue
        if not name.endswith("Adapter") or cls.__module__ != base.__name__:
            continue
        takes_user = any(
            "user" in inspect.signature(getattr(cls, method)).parameters
            for method in vars(cls)
            if callable(getattr(cls, method, None)) and not method.startswith("_")
        )
        if not takes_user:
            assert not cls.carries_user, (
                f"{name} declares carries_user=True but no method of it takes a `user`; "
                "a call made as a user does not reach the backend as that user"
            )
