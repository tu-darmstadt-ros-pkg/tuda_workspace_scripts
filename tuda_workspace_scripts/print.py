from os import write
from shutil import get_terminal_size
from sys import stderr, stdout
from textwrap import wrap


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    ORANGE = "\033[0;33m"
    BLUE = "\033[0;34m"
    PURPLE = "\033[0;35m"
    CYAN = "\033[0;36m"
    LGRAY = "\033[0;37m"
    DGRAY = "\033[1;30m"
    LRED = "\033[1;31m"
    LGREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    LBLUE = "\033[1;34m"
    LPURPLE = "\033[1;35m"
    LCYAN = "\033[1;36m"
    WHITE = "\033[1;37m"
    Error = "\033[0;31m"
    Warning = "\033[0;33m"
    Info = "\033[0;34m"
    Success = "\033[0;32m"
    RESET = "\033[0;39m"


class Style:
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    REVERSE = "\033[7m"
    RESET = "\033[0m"


def print_color(color, message, file=stdout):
    print(f"{color}{message}{Colors.RESET}", file=file)


def print_header(message, file=stdout):
    print_color(Colors.LBLUE, f">>> {message}", file)


def print_subheader(message, file=stdout):
    print_color(Colors.CYAN, f"=== {message}", file)


def print_info(message, file=stdout):
    print_color(Colors.Info, message, file)


def print_success(message, file=stdout):
    print_color(Colors.Success, message, file)


def print_warn(message, file=stdout):
    print_color(Colors.Warning, message, file)


def print_error(message, file=stderr):
    print_color(Colors.Error, message, file)


def confirm(question):
    """
    Prompts the user to confirm a question with yes or no.
    """
    while True:
        answer = input(f"{question} [Y/n]: ").lower()
        if answer == "y" or answer == "yes":
            return True
        if answer == "n" or answer == "no":
            return False
        print("I did not quite catch that! Please answer yes or no.")


def print_workspace_error():
    """
    Print an error message that no workspace is configured.
    """
    print_error("No workspace configured!")
    print_info(
        "Plese create a workspace, source it and mark the root folder containing src, build and install as a ros2 workspace using:"
    )
    print("tuda_wss init")


class StatusOutput:
    """
    Formats output to only show the line_count last lines that were written.
    If you use this class make sure to wrap your main in a try finally and call StatusOutput.reset()
    in the finally handler to avoid breaking the terminal on abnormal exit
    """

    def __init__(self, line_count: int, file=stdout) -> None:
        self.line_count = line_count
        self._lines = []
        self._file = file
        self._overwrite_disabled = False

    def disable_overwrite(self):
        """
        Disables overwriting previous lines and therefore the line limit.
        Following status calls will simply append to the output.
        """
        self._overwrite_disabled = True

    def status(self, msg) -> None:
        """
        Add a status line to the status output. If more than line_count lines are added, the oldest lines are removed.
        """
        if self._overwrite_disabled:
            self._file.write(f"{msg}\r\n")
            return
        lines = msg.split("\n")
        if len(self._lines) > 0:
            self._move_lines_up(len(self._lines))
        self._lines += lines
        if len(self._lines) > self.line_count:
            self._lines = self._lines[-self.line_count :]
        self._write_status()

    def info(self, message, clear_status=True) -> None:
        """
        Print a message to the console and clear the status output unless clear_status is set to False
        The info will be printed above the status output if it is preserved.
        """
        self._move_lines_up(len(self._lines))
        print_info(message)
        if clear_status:
            self._lines = []
        for line in self._lines:
            self._file.write(f"\033[K{line}\r\n")
        self._write_status()

    def clear(self):
        """
        Delete all status output from the console.
        """
        if len(self._lines) > 0:
            self._move_lines_up(len(self._lines))
            self._file.write(f"\033[J")
        self._lines = []

    def _move_lines_up(self, count):
        if count > 0:
            self._file.write(f"\033[{count}A")

    def _write_status(self):
        try:
            self._file.write("\033[?7l")
            for line in self._lines:
                self._file.write(f"\033[K{line}\r\n")
            self._file.flush()
        finally:
            self._file.write("\033[?7h")


class TableOutput:
    def __init__(
        self, columns: list[str], file=stdout, max_width=get_terminal_size().columns
    ) -> None:
        self._columns = columns
        self._max_width = max_width
        self._file = file
        self._lines = []

    def add_row(self, row: list[str]):
        self._lines.append(row)

    def print(self):
        # Find the longest string in each column
        column_widths = [len(column) for column in self._columns]
        for row in self._lines:
            for i, column in enumerate(row):
                column_widths[i] = max(column_widths[i], len(column))
        # Add spacing of 4 to each column except the last one (since it is left-justified)
        column_widths = [column_width + 4 for column_width in column_widths]
        column_widths[-1] -= 4
        # Make sure the table fits on the screen
        if sum(column_widths) > self._max_width:
            # The table is too wide. We iteratively distribute space, first evenly and unneeded space goes back to the pool
            # and then we distribute the remaining space evenly
            last_column_width = 0
            column_width = self._max_width // len(column_widths)
            while last_column_width != column_width:
                last_column_width = column_width
                used_width = 0
                larger_columns = 0
                for width in column_widths:
                    if width < column_width:
                        used_width += width
                    else:
                        larger_columns += 1
                column_width = (self._max_width - used_width) // larger_columns
            column_widths = [min(column_width, w) for w in column_widths]

        # Print the header
        self._print_row(self._columns, column_widths)
        # Print the separator
        self._file.write("\033[K" + "=" * sum(column_widths) + "\r\n")
        # Print the rows
        for row in self._lines:
            self._print_row(row, column_widths)
        self._file.flush()

    def _print_row(self, row: list[str], column_widths: list[int], align="left"):
        # Split into lines if necessary
        columns = [[] for _ in row]
        for i, column in enumerate(row):
            colwidth = column_widths[i]
            lines = [
                line
                for col in column.split("\n")
                for line in wrap(col, colwidth, tabsize=4)
            ]
            columns[i] = lines
        # Write all lines for each column one line after the other. Empty columns in a line are filled with spaces
        for n in range(max([len(column) for column in columns])):
            for i in range(len(row)):
                if n < len(columns[i]):
                    text = columns[i][n]
                    if align == "right":
                        self._file.write(text.rjust(column_widths[i]))
                    elif align == "center":
                        self._file.write(text.center(column_widths[i]))
                    else:
                        self._file.write(text.ljust(column_widths[i]))
                else:
                    self._file.write(" " * column_widths[i])
            self._file.write("\r\n")
