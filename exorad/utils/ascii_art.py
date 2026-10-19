from exorad.__version__ import __version__

# ascii_art ="   .-.      _______                             .  '  *   .  . \n\
#                   {}``; |==|_______D                          .  * * -+-    \n\
#               (  /  |        / | \                               * .  ' .    \n\
#                \(_)_]]      /  |  \                            *   *  .   .\n "


ascii_art_part1 = "   .-.      _______                             .  '  *   .  . \n\
                  {}``; |==|_______D               ExoRad     .  * * -+-    \n\
              (  /  |        / | \\                    "
ascii_art_part2 = "  * .  ' .    \n\
               \\(_)_]]      /  |  \\                            *   *  .   .\n "
ascii_art = f"{ascii_art_part1}{__version__}{ascii_art_part2}"

ascii_plot_part1 = "  .    _     *       \\|/   .       .      -*-              +\n\
    .'\\ \\`.     +    -*-     *   .         '       .   *\n\
 .  |__''_|  .       /|\\ +         .    +       .           |\n\
    |     |           `  .    '             . *   .    +    '\n\
  _.'-----'-._     *  ExoRad-plot     .\n\
/             \\__.__.--.__"

ascii_plot_part2 = "__"

ascii_plot = f"{ascii_plot_part1}{__version__}{ascii_plot_part2}"
