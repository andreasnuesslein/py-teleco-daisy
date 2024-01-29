from dataclasses import dataclass
from typing import Literal

import requests

base_url = "https://tmate.telecoautomation.com/"


@dataclass
class DaisyStatus:
    idInstallationDeviceStatusitem: int
    idDevicetypeStatusitemModel: int
    statusitemCode: str
    statusItem: str
    statusValue: str
    lowlevelStatusitem: None


@dataclass
class DaisyInstallation:
    activetimer: str
    firmwareVersion: str
    idInstallation: int
    idInstallationDevice: int
    instCode: str
    instDescription: str
    installationOrder: int
    latitude: float
    longitude: float
    weekend: str  # list[str]
    workdays: str  # list[str]


@dataclass
class DaisyDevice:
    activetimer: str
    deviceCode: str
    deviceIndex: int
    deviceOrder: int
    directOnly: None
    favorite: str
    feedback: str
    idDevicemodel: int
    idDevicetype: int
    idInstallationDevice: int
    label: str
    remoteControlCode: str

    client: "TelecoDaisy"
    installation: DaisyInstallation

    def update_state(self) -> list[DaisyStatus]:
        return self.client.status_device_list(self.installation, self)


class DaisyCover(DaisyDevice):
    position: int | None = None
    is_closed: bool | None = None

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "OPEN_CLOSE":
                self.is_closed = status.statusValue == "CLOSE"
            if status.statusitemCode == "LEVEL":
                self.position = int(status.statusValue)

    def open_cover(self, percent: Literal["33", "66", "100"] = "100"):
        percent_map = {"33": "CH2", "66": "CH3", "100": "CH4"}
        self._control_cover(percent_map[percent])

    def close_cover(self):
        self._control_cover("CH1")

    def stop_cover(self):
        self._control_cover("CH7")

    def _control_cover(self, level: Literal["CH1", "CH2", "CH3", "CH4", "CH7"]):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(
                        self.deviceIndex
                    ),  # Note: was "2", deviceIndex might be wrong
                    "idInstallationDevice": self.idInstallationDevice,
                    # "commandAction": "LEVEL",
                    "lowlevelCommand": level,
                }
            ],
        )


class DaisyLight(DaisyDevice):
    is_on: bool | None = None
    brightness: int | None = None  # from 0 to 100
    rgb: tuple[int, int, int] | None = None

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "POWER":
                self.is_on = status.statusValue == "ON"
            if status.statusitemCode == "COLOR":
                val = status.statusValue
                self.brightness = int(val[1:4])
                self.rgb = (int(val[5:8]), int(val[9:12]), int(val[13:16]))

    def set_rgb_and_brightness(
        self, rgb: tuple[int, int, int] = None, brightness: int = None
    ):
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
                    "deviceCode": str(
                        self.deviceIndex
                    ),  # Note: was "3", deviceIndex might be wrong
                    "idInstallationDevice": self.idInstallationDevice,
                }
            ],
        )

    def turn_off(self):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "POWER",
                    "commandId": 138,
                    "commandParam": "OFF",
                    "deviceCode": str(
                        self.deviceIndex
                    ),  # Note: was "3", deviceIndex might be wrong
                    "idInstallationDevice": self.idInstallationDevice,
                }
            ],
        )


@dataclass
class DaisyRoom:
    idInstallationRoom: int
    idRoomtype: int
    roomDescription: str
    roomOrder: int
    deviceList: list[DaisyDevice]


class TelecoDaisy:
    idAccount: int | None = None
    idSession: str | None = None

    def __init__(self, email, password):
        self.s = requests.Session()
        self.s.auth = ("teleco", "tmate20")
        self.email = email
        self.password = password

    def login(self):
        login = self.s.post(
            base_url + "teleco/services/account-login",
            json={"email": self.email, "pwd": self.password},
        )
        login_json = login.json()
        if login_json["codEsito"] != "S":
            raise Exception(login_json)

        self.idAccount = login_json["valRisultato"]["idAccount"]
        self.idSession = login_json["valRisultato"]["idSession"]

    def get_account_installation_list(self) -> list[DaisyInstallation]:
        req = self.s.post(
            base_url + "teleco/services/account-installation-list",
            json={"idSession": self.idSession, "idAccount": self.idAccount},
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        installations = []
        for inst in req_json["valRisultato"]["installationList"]:
            installations += [DaisyInstallation(**inst)]
        return installations

    def get_room_list(self, installation: DaisyInstallation) -> list[DaisyRoom]:
        req = self.s.post(
            base_url + "teleco/services/room-list",
            json={
                "idSession": self.idSession,
                "idAccount": self.idAccount,
                "idInstallation": installation.idInstallation,
            },
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        rooms = []
        for room in req_json["valRisultato"]["roomList"]:
            devices = []
            for device in room.pop("deviceList"):
                if device["idDeviceType"] == 23:
                    devices += [
                        DaisyLight(**device, client=self, installation=installation)
                    ]
                elif device["idDeviceType"] == 24:
                    devices += [
                        DaisyCover(**device, client=self, installation=installation)
                    ]
            rooms += [DaisyRoom(**room, deviceList=devices)]
        return rooms

    def status_device_list(
        self, installation: DaisyInstallation, device: DaisyDevice
    ) -> list[DaisyStatus]:
        req = self.s.post(
            base_url + "teleco/services/status-device-list",
            json={
                "idSession": self.idSession,
                "idAccount": self.idAccount,
                "idInstallation": installation.idInstallation,
                "idInstallationDevice": device.idInstallationDevice,
            },
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        return [DaisyStatus(**x) for x in req_json["valRisultato"]["statusitemList"]]

    def feed_the_commands(
        self, installation: DaisyInstallation, commandsList: list[dict]
    ):
        req = self.s.post(
            base_url + "teleco/services/tmate20/feedthecommands/",
            json={
                "commandsList": commandsList,
                "idInstallation": installation.instCode,
                "idSession": self.idSession,
                "idScenario": 0,
                "isScenario": False,
            },
        )
        req_json = req.json()
        if req_json["MessageID"] == "WS-000":
            return True
        raise Exception(req_json)
