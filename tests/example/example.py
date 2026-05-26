import epics


class example_pv:
    pv = None

    def get(self):
        if self.pv is None:
            self.pv = epics.PV("EXAMPLE:PV")
        return self.pv.get(as_string=True)
