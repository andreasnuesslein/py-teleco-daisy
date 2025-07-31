from time import sleep
from typing import Annotated, Any, Literal

import requests
from pydantic import BaseModel, ConfigDict, Field

base_url = "https://tmate.telecoautomation.com/"


class DaisyStatus(BaseModel):
    """for /status-device-list"""

    idInstallationDeviceStatusitem: int
    idDevicetypeStatusitemModel: int
    statusitemCode: str
    statusItem: str
    statusValue: str
    lowlevelStatusitem: None | str = None


class DaisyInstallation(BaseModel):
    activetimer: str
    firmwareVersion: str
    idInstallation: int
    idInstallationDevice: int
    instCode: str
    instDescription: str
    installationOrder: int
    latitude: float | None
    longitude: float | None
    weekend: str | None  # list[str]
    workdays: str | None  # list[str]

    def __str__(self):
        return f"DaisyInstallation fw{self.firmwareVersion}"


class DaisyBaseDevice(BaseModel):
    activetimer: str
    deviceCode: str
    deviceIndex: int
    deviceOrder: int
    directOnly: str | None = None
    favorite: str
    feedback: str
    idDevicemodel: int
    idDevicetype: int
    idInstallationDevice: int
    label: str
    remoteControlCode: str


class DaisyDevice(DaisyBaseDevice):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: "TelecoDaisy"
    installation: DaisyInstallation

    def update_state(self) -> list[DaisyStatus]:
        return self.client.status_device_list(self.installation, self)


class DaisyDeviceWithCommands(DaisyBaseDevice):
    class DeviceCommand(BaseModel):
        commandAction: str
        commandCode: str
        commandParam: str
        deviceIndex: int
        idDevicetypeCommandModel: int
        idInstallationDeviceCommand: int
        lowlevelCommand: str

    deviceCommandList: list[DeviceCommand]

    def __str__(self):
        return f'DaisyDevice "{self.label}" (type: {self.idDevicetype})'


class DaisyBaseRoom(BaseModel):
    idInstallationRoom: int
    idRoomtype: int
    roomDescription: str
    roomOrder: int
    deviceList: list[DaisyDevice]

    def __str__(self):
        return f'DaisyRoom "{self.roomDescription}"'


class DaisyRoomWithCommands(DaisyBaseRoom):
    deviceList: list[DaisyDeviceWithCommands]


class DaisyCover(DaisyDevice):
    position: int | None = None
    is_closed: bool | None = None

    osc_map: dict[Literal["open", "stop", "close"], dict[str, Any]]

    def __str__(self):
        return f'DaisyCover "{self.label}"'

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "OPEN_CLOSE":
                match status.statusValue:
                    case "CLOSE":
                        self.is_closed = True
                    case "OPEN":
                        self.is_closed = False
                    case _:
                        self.is_closed = None
            if status.statusitemCode == "LEVEL":
                self.position = int(status.statusValue)
        return stati

    def open_cover(self, percent: Literal["33", "66", "100"] | None = None):
        if percent == "100":
            return self._open_stop_close("open")
        return self._control_cover(percent)

    def stop_cover(self):
        self._open_stop_close("stop")

    def close_cover(self):
        self._open_stop_close("close")

    def _open_stop_close(self, open_stop_close: Literal["open", "stop", "close"]):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                    "commandAction": "OPEN_STOP_CLOSE",
                }
                | self.osc_map[open_stop_close]
            ],
        )

    def _control_cover(self, percent: Literal["33", "66", "100"]):
        percent_map = {
            "33": ["LEV2", 97, "CH2"],
            "66": ["LEV3", 98, "CH3"],
            "100": ["LEV4", 99, "CH4"],
        }
        c_param, c_id, c_ll = percent_map[percent]

        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                    "commandAction": "LEVEL",
                    "commandId": c_id,
                    "commandParam": c_param,
                    "lowlevelCommand": c_ll,
                }
            ],
        )


class DaisyAwningsCover(DaisyCover):
    idDevicetype: Literal[22]

    osc_map: dict[Literal["open", "stop", "close"], dict[str, Any]] = {
        "open": {"commandId": 75, "commandParam": "OPEN", "lowlevelCommand": "CH5"},
        "stop": {"commandId": 76, "commandParam": "STOP", "lowlevelCommand": "CH7"},
        "close": {"commandId": 77, "commandParam": "CLOSE", "lowlevelCommand": "CH8"},
    }


class DaisySlatsCover(DaisyCover):
    idDevicetype: Literal[24]

    osc_map: dict[Literal["open", "stop", "close"], dict[str, Any]] = {
        "open": {"commandId": 94, "commandParam": "OPEN", "lowlevelCommand": "CH4"},
        "stop": {"commandId": 95, "commandParam": "STOP", "lowlevelCommand": "CH7"},
        "close": {"commandId": 96, "commandParam": "CLOSE", "lowlevelCommand": "CH1"},
    }


class DaisyLight(DaisyDevice):
    is_on: bool | None = None
    brightness: int | None = None  # from 0 to 100
    rgb: tuple[int, int, int] | None = None

    def __str__(self):
        return f'DaisyLight "{self.label}"'

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "POWER":
                self.is_on = status.statusValue == "ON"
            if status.statusitemCode == "COLOR":
                val = status.statusValue
                self.brightness = int(val[1:4])
                self.rgb = (int(val[5:8]), int(val[9:12]), int(val[13:16]))
        return stati

    def _set_rgb_and_brightness(
        self,
        rgb: tuple[int, int, int] | None = None,
        brightness: int | None = None,
        specific_params: dict | None = None,
    ):
        if specific_params is None:
            specific_params = {}
        if brightness is None:
            brightness = self.brightness or 0
        if 0 > brightness or brightness > 100:
            raise ValueError("Brightness must be between 0 and 100")
        if rgb is None:
            rgb = self.rgb or (255, 255, 255)
        if any((c < 0 or c > 255) for c in rgb):
            raise ValueError("Color must be between 0 and 255")

        v = f"A{brightness:03d}R{rgb[0]:03d}G{rgb[1]:03d}B{rgb[2]:03d}"

        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "COLOR",
                    "commandId": 137,
                    "commandParam": v,
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                }
                | specific_params
            ],
        )

    def _turn_on(self, specific_params: dict):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "POWER",
                    "commandParam": "ON",
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                }
                | specific_params
            ],
        )

    def _turn_off(self, specific_params: dict):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "POWER",
                    "commandId": 138,
                    "commandParam": "OFF",
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                    "lowlevelCommand": None,
                }
                | specific_params
            ],
        )


class DaisyRGBLight(DaisyLight):
    idDevicetype: Literal[23]

    def set_rgb_and_brightness(
        self, rgb: tuple[int, int, int] | None = None, brightness: int | None = None
    ):
        return self._set_rgb_and_brightness(
            rgb, brightness, {"commandId": 137, "lowlevelCommand": None}
        )

    def turn_on(self):
        return self._turn_on({"commandId": 138, "lowlevelCommand": None})

    def turn_off(self):
        return self._turn_off({"commandId": 138, "lowlevelCommand": None})


class DaisyWhiteLight(DaisyLight):
    idDevicetype: Literal[21, 25]

    def set_rgb_and_brightness(
        self, rgb: tuple[int, int, int] | None = None, brightness: int | None = None
    ):
        return self._set_rgb_and_brightness(
            rgb, brightness, {"commandId": 146, "lowlevelCommand": "CH1"}
        )

    def turn_on(self):
        return self._turn_on({"commandId": 146, "lowlevelCommand": "CH1"})

    def turn_off(self):
        return self._turn_off({"commandId": 147, "lowlevelCommand": "CH8"})


DaisyDeviceUnion = Annotated[
    DaisyAwningsCover | DaisySlatsCover | DaisyWhiteLight | DaisyRGBLight,
    Field(discriminator="idDevicetype"),
]


class DaisyRoom(DaisyBaseRoom):
    deviceList: list[DaisyDeviceUnion]


class TelecoDaisy:
    idAccount: int | None = None
    idSession: str | None = None

    def __init__(self, email, password):
        self.s = requests.Session()
        self.s.auth = ("teleco", "tmate20")
        self.email = email
        self.password = password

    def _tmate20_post(self, url, json: dict | None = None) -> dict:
        payload = {"idSession": self.idSession}
        if json:
            payload |= json
        req = self.s.post(base_url + url, json=payload)
        return req.json()

    def _post(self, url, json: dict | None = None, unauth=False) -> dict:
        if unauth:
            _json = json
        else:
            _json = {"idSession": self.idSession, "idAccount": self.idAccount}
            if json:
                _json |= json
        req = self.s.post(base_url + url, json=_json)
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)
        return req_json["valRisultato"]

    def login(self):
        login = self._post(
            "teleco/services/account-login",
            {"email": self.email, "pwd": self.password},
            unauth=True,
        )
        self.idAccount = login["idAccount"]
        self.idSession = login["idSession"]

    def get_account_installation_list(self) -> list[DaisyInstallation]:
        req = self._post("teleco/services/account-installation-list")

        return [DaisyInstallation(**inst) for inst in req["installationList"]]

    def get_installation_is_active(self, installation: DaisyInstallation):
        res = self._tmate20_post(
            "teleco/services/tmate20/nodestatus/",
            {"idInstallation": installation.instCode},
        )
        return res["nodeActive"]

    def get_room_configuration_list(self, installation: DaisyInstallation):
        req = self._post(
            "teleco/services/room-configuration-list",
            {"idInstallation": installation.idInstallation},
        )
        return [DaisyRoomWithCommands(**dr) for dr in req["roomList"]]

    def get_room_list(self, installation: DaisyInstallation) -> list[DaisyRoom]:
        room_list = self._post(
            "teleco/services/room-list",
            {"idInstallation": installation.idInstallation},
        )

        rooms = []
        for room in room_list["roomList"]:
            for dv in room["deviceList"]:
                dv["installation"] = installation
                dv["client"] = self
            rooms += [DaisyRoom(**room)]

        return rooms

    def status_device_list(
        self, installation: DaisyInstallation, device: DaisyDevice
    ) -> list[DaisyStatus]:
        status_device_list = self._post(
            "teleco/services/status-device-list",
            {
                "idInstallation": installation.idInstallation,
                "idInstallationDevice": device.idInstallationDevice,
            },
        )

        return [DaisyStatus(**x) for x in status_device_list["statusitemList"]]

    def _scenario_list(self, installation: DaisyInstallation):
        req = self._post(
            "teleco/services/scenario-list",
            {
                "idInstallation": installation.idInstallation,
            },
        )

        return req

    def _command_scenario_list(self, installation: DaisyInstallation, szenario_id):
        req = self._post(
            "teleco/services/command-scenario-list",
            json={
                "idInstallation": installation.idInstallation,
                "idInstallationScenario": szenario_id,
            },
        )
        return req

    def feed_the_commands(
        self,
        installation: DaisyInstallation,
        commandsList: list[dict],
        ignore_ack=False,
    ):
        res = self._tmate20_post(
            "teleco/services/tmate20/feedthecommands/",
            json={
                "commandsList": commandsList,
                "idInstallation": installation.instCode,
                "idScenario": 0,
                "isScenario": False,
            },
        )
        if res["MessageID"] != "WS-000":
            raise Exception(res)

        if ignore_ack:
            return {"success": None}

        return self._get_ack(installation, res["ActionReference"])

    def _get_ack(self, installation: DaisyInstallation, action_reference: str):
        res = self._tmate20_post(
            "teleco/services/tmate20/getackcommand/",
            json={
                "id": action_reference,
                "idInstallation": installation.instCode,
                "idSession": self.idSession,
            },
        )
        if res["MessageID"] != "WS-300":
            raise AssertionError()
        if res["MessageText"] == "RCV":
            sleep(0.5)
            return self._get_ack(installation, action_reference)
        if res["MessageText"] == "PROC":
            return {"success": True}
        return {"success": False}
