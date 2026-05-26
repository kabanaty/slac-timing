def test_lazy_pv():
    from slicops import unit_util

    with unit_util.start_ioc("example.yaml", db_yaml="db.yaml"):
        import epics

        assert len(epics.ca._cache) == 0
        assert epics.caget("EXAMPLE:PV", as_string=True) == "hello"
    epics.ca.finalize_libca()


def test_lazy_2_pv():
    from slicops import unit_util
    import epics

    with unit_util.start_ioc("example.yaml", db_yaml="db.yaml"):
        epics.ca.initialize_libca()
        assert len(epics.ca._cache) == 0
        assert epics.caget("EXAMPLE:PV", as_string=True) == "hello"
