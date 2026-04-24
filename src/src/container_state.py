class _BaseContainerState:
    PRE_EXPORT = "pre_export"
    LOADED = "loaded"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    DISCHARGED = "discharged"
    DELIVERED = "delivered"

    PRE_EXPORT_CODES = {"CEP", "CPS", "CGI"}
    LOADED_CODES = {"CLL", "CLT"}
    DEPARTED_CODES = {"VDL", "VDT"}
    ARRIVED_CODES = {"VAT", "VAD", "TSD"}
    DISCHARGED_CODES = {"CDT", "CDD"}
    DELIVERED_CODES = {"CGO", "CDC", "CER"}

    def __init__(self):
        self.reset()

    def reset(self):
        self.current_state_value = self.PRE_EXPORT

    def advance(self, code):
        if code in self.PRE_EXPORT_CODES:
            self.current_state_value = self.PRE_EXPORT
        elif code in self.LOADED_CODES:
            self.current_state_value = self.LOADED
        elif code in self.DEPARTED_CODES:
            self.current_state_value = self.DEPARTED
        elif code in self.ARRIVED_CODES:
            self.current_state_value = self.ARRIVED
        elif code in self.DISCHARGED_CODES:
            self.current_state_value = self.DISCHARGED
        elif code in self.DELIVERED_CODES:
            self.current_state_value = self.DELIVERED


class ContainerState(_BaseContainerState):
    pass


class FastContainerStateTracker(_BaseContainerState):
    pass


