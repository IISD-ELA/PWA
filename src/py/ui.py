# This file holds any functions or features related to UI for the model generation and calibration process.


class usr_input:
    def string(self, description, default_value=None):
        """
        Prompt the user for a string input with a description.
        If no input is provided, return the default value if specified.
        """
        prompt = f"Enter {description} (default: {default_value}): "
        user_input = input(prompt).strip()
        if user_input == "" and default_value is not None:
            print(f"No {description} provided. Default applied ('{default_value}').")
            return default_value
        elif user_input == "":
            while user_input == "":
                user_input = input(f"A value is required. " + prompt).strip()
        return user_input
    
    def file(self, description, default_value=None):
        """
        Prompt the user for a file name input with a description.
        If no input is provided, return the default value if specified.
        """
        prompt = f"Enter {description} filename (e.g., '{default_value}'). " + \
                "If entering multiple raster files, separate them with commas (e.g., raster1,raster2,raster3) "
        filename = input(prompt)
        if description == "LiDAR DEM raster" and "," in filename:
            filename = [f.strip() for f in filename.split(",")]
            if default_value is None and filename == "":
                while filename == "":
                    filename = input(f"A file name is required. " + prompt).strip()
            elif filename == "":
                filename = default_value
                print(f"No {description} name provided. Default applied ('{default_value}').")
        else:
            filename = filename.strip()
            if "." in filename:
                filename = input("Please do not include file extension in the name. " + prompt).strip()
            elif default_value is None and filename == "":
                while filename == "":
                    filename = input(f"A file name is required. " + prompt).strip()
            elif filename == "":
                filename = default_value
                print(f"No {description} name provided. Default applied ('{default_value}').")
        return filename
