import sys

from pydantic import ValidationError

from teleco_daisy import TelecoDaisy


def discover(user, passwd):
    client = TelecoDaisy(user, passwd)
    client.login()

    # different daisy boxes
    installations = client.get_account_installation_list()
    for installation in installations:
        print("# INSTALLATION")
        print(installation)
        print(client.get_installation_is_active(installation))

        print("\n## ROOM CONFIGURATIONS")
        rooms = client.get_room_configuration_list(installation)
        for room in rooms:
            print(room)
            print("\n### DEVICE COMMANDS")
            for device in room.deviceList:
                print(device)

                for command in device.deviceCommandList:
                    print(f"  {command.model_dump()}")

        print("\n## ROOM LIST")
        try:
            rooms = client.get_room_list(installation)
        except ValidationError as e:
            print("\n\n")
            print(e)
            print("\n\nYou most likely have a device that is not supported yet.")
            print("Create an issue and add all the output from above.")

            sys.exit(1)
        for room in rooms:
            print(room)
            print("\n### DEVICE STATI")
            for device in room.deviceList:
                print(device)
                for status in device.update_state():
                    print(f"  {status.model_dump()}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python discover.py <email> <password>")
        sys.exit(1)

    discover(sys.argv[1], sys.argv[2])
