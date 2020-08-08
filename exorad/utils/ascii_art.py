import exorad.__version__ as version

# ascii_art ="   .-.      _______                             .  '  *   .  . \n\
#                   {}``; |==|_______D                          .  * * -+-    \n\
#               (  /  |        / | \                               * .  ' .    \n\
#                \(_)_]]      /  |  \                            *   *  .   .\n "


ascii_art_part1 = "   .-.      _______                             .  '  *   .  . \n\
                  {}``; |==|_______D               ExoRad     .  * * -+-    \n\
              (  /  |        / | \                    "
ascii_art_part2 = "  * .  ' .    \n\
               \(_)_]]      /  |  \                            *   *  .   .\n "
ascii_art = '{}{}{}'.format(ascii_art_part1, version, ascii_art_part2)

ascii_plot_part1 = "  .    _     *       \|/   .       .      -*-              +\n\
    .'\ \`.     +    -*-     *   .         '       .   *\n\
 .  |__''_|  .       /|\ +         .    +       .           |\n\
    |     |           `  .    '             . *   .    +    '\n\
  _.'-----'-._     *  ExoRad-plot     .\n\
/             \__.__.--.__"

ascii_plot_part2 = "__"

ascii_plot = '{}{}{}'.format(ascii_plot_part1, version, ascii_plot_part2)
