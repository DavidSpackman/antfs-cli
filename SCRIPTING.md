Scripting
==============================================================================

In the location for scripts, usually ~/.config/antfs-cli/scripts
(but see README, for more precise location) you can add executable scripts
and programs.

The scripts and programs placed here will be executed in the background when
a file has been downloaded. (Upload and delete actions are defined below but
not currently triggered by `antfs-cli`.)

Every file in the folder is run, in alphabetical order, so a numeric prefix
such as `40-` sets the order. Each must be executable (`chmod +x`) and start
with a `#!` line. Each downloaded file gets its own background run of the
scripts, so several runs can happen at the same time; a script that keeps
state (such as login tokens) should lock it.

The three arguments to the executables are:

 - Action (DOWNLOAD, UPLOAD or DELETE -- depending on what action caused the
   script to run)

 - File name

 - FIT type (e.g. 4 for an Activity, see File.Identifier in ant/fs/file.py
   for other FIT file types)

Note: Do not modify, delete, or rename the original file. If you want to
modify or change the file, create a copy, or write the new data to a different
file.

Example
---------------------

    #!/usr/bin/env python3

    import sys

    def upload(action, filename, fittype):
        # if we downloaded a new activity
        if action == "DOWNLOAD" and fittype == 4:
            data = open(filename, 'rb').read()
            # upload file
            pass

    if __name__ == "__main__":
        upload(sys.argv[1], sys.argv[2], int(sys.argv[3]))



