File list

    README.txt               : This file.
    INSTALL.txt              : Installation documentation.
    ../src/man/man1/wcd.txt  : Manual, text format.
    ../src/man/man1/wcd.htm  : Manual, HTML format.
    whatsnew.txt             : Change log.
    faq.txt                  : Frequently Asked Questions.
    copying.txt              : distribution license.
    problems.txt             : Known problems.
    todo.txt                 : Things to do.


Table of Contents

       1.0 History

       2.0 Copyright
           2.1 C3PO data structures
           2.2 DOSDIR
           2.3 Recmatch
           2.4 Ninux Czo Directory
           2.5 Miscellaneous bits and pieces

       3.0 Acknowledgements
           3.1 Translators
           3.2 Works of others used in the program

       4.0 Contact and Download information

1.0 History

        In 1995 I started working for Philips Research in Eindhoven. I
        had to do all my work on HP Unix (HP-UX). I was missing an
        application like Norton Change Directory (NCD). I didn't know
        of any other NCD like program so in 1996 I decided to make it
        myself. On the internet I found Jason Mathew's DOSDIR package
        in the Simtel archives. DOSDIR was my starting point. Because
        DOSDIR was portable I could make wcd at home with Borland-C
        3.1 on my PC (intel 80486, 80 MHz) on DOS 6.2. I mailed the
        source code to work and there I build a version for HP-UX. I
        made wcd for myself, but was happy to share it with others.
        Some colleagues started using wcd.

        In 1997, I found the DJGPP compiler and used that as my main
        development environment. Now I was able to create a 32 bit DOS
        version, and it supported long directory names under Windows
        95.

        In Dec 1997 I put wcd on the internet. I was amazed that
        already 7 people downloaded it in the first month. From then
        on development was driven a lot by feedback I got via the
        internet. In March 1998 the GNU distribution license was
        attached to version 2.0.0.

        Later I installed Linux (RedHat 5.0) on my PC at home and
        that became my main development platform.

        Because eventually most DOS users will migrate to Windows I
        ported wcd to Windows NT. I started with Borland C 4.0, but
        changed soon to the MinGW compiler. The first Win32 port was
        ready in November 1999.
        The DOS 32 bit version still stayed the most popular version for
        a long time. In 2003 the Windows NT port became most popular.

        In April 2000 (version 2.3.0) a curses based interface was added
        to have a consistent interface on all platforms. And a year later
        the 'graphical tree' curses interface was added (version 3.0.0).

        I used wcd mainly in an ASCII (C) environment. Only since version 3.2.0
        in Dec 2005 eight bit characters sets were properly supported.

        After a development pause of two years, version 4.0.0 (Sep 2008) was
        the first which supported internationalization by message translations
        via gettext.

        Since version 5.0.0 (Mar 2009) wcd supports Unicode, to enable
        internationalization for all languages. In the beginning this
        development was done on Linux, and later on Cygwin which supports
        Unicode since version 1.7.

        In version 6.0.0 (Feb 2017) the DOSDIR directory interface layer was
        removed from Wcd.  The amount of directories can be huge these days,
        so scanning a disk can take a long time. Removal of DOSDIR resulted in
        faster disk scanning on Windows and Unix.


2.0 Copyright


        Copyright (C) 1996-2023 Erwin Waterlander

        This program is free software; you can redistribute it and/or
        modify it under the terms of the GNU General Public License
        as published by the Free Software Foundation; either version 2
        of the License, or (at your option) any later version.

        This program is distributed in the hope that it will be useful,
        but WITHOUT ANY WARRANTY; without even the implied warranty of
        MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
        GNU General Public License for more details.

        Visit <https://www.gnu.org/copyleft/gpl.html>


    2.1 C3PO data structures

        Data structures with dynamic memory allocation were created
        with Ondrej Popp's C3PO ( Compiler Compiler Compiler Popp
        Ondrej ).

        https://sourceforge.net/projects/c3po/
        email: <ondrejpopp@users.sourceforge.net>

    2.2 DOSDIR

        Wcd used DOSDIR for scanning the disk until Wcd version 5.3.4. Only
        the parts of DOSDIR that are distributed under GNU General Public
        License were used in WCD.

        DOSDIR: A Portable DOS/UNIX/VMS Directory Interface

        DOSDIR minimizes the OS-specific directory access code for
        applications allowing programmers to concentrate on the
        application itself and not on the low-level directory and file
        structure. DOSDIR applications will run on their native
        operating systems with the appropriate file syntax and
        handling, which is expected for that platform.

        Copyright (C) 1994 Jason Mathews.

                Jason Mathews
                The MITRE Corporation
           202 Burlington Road
           Bedford, MA 01730-1420

           Email: mathews@mitre.org, mathews@computer.org

        DOSDIR can be download from my own homepage
        https://waterlan.home.xs4all.nl/

    2.3 Recmatch

        I used the regular matching algorithm, recmatch(), of
        Info-Zip's unzip program.

        recmatch() was written by Mark Adler.

        Copyright (C) 1990-1992 Mark Adler, Richard B. Wales, Jean-loup Gailly,
        Kai Uwe Rommel and Igor Mandrichenko.

        Mark Adler (original Zip author; UnZip decompression; writer
        of recmatch() ) and Greg Roelofs (former UnZip
        maintainer/co-author) have given permission to me to
        distribute recmatch() (match.c,match.h) under the GNU General
        Public License conditions as long as there's some sort of
        comment included that indicates it came from Info-ZIP's
        UnZip/Zip and was written by Mark Adler.

           Info-ZIP's home WWW site is at:

            https://sourceforge.net/projects/infozip/

    2.4 Ninux Czo Directory

        Ideas and source code of NCD (Ninux Czo Directory) have been
        used in the WCD graphical interface.

        Ninux Change Directory
        Copyright (C) 1995 Borja Etxebarria
        <borja@bips.bi.ehu.es> or <jtbecgob@s835cc.bi.ehu.es>
        https://www.ibiblio.org/pub/Linux/utils/shell/ncd-0.9.8.tgz

        Additions on NCD were made by Olivier Sirol (Czo)

        Ninux Czo Directory
        Copyright (C) 1995 Borja Etxebarria
        Copyright (C) 1996 Olivier Sirol
        Olivier Sirol <sirol@ecoledoc.ibp.fr>
        https://www.ibiblio.org/pub/Linux/utils/file/managers/ncd1_205.tgz

    2.5 Miscellaneous bits and pieces

        wcd_fixpath() is a modified version of _fixpath() Copyright
        (C) 1995-1996 DJ Delorie, see COPYING.DJ for details

        _fixpath() is a library function of libc for DJGPP. See also
        https://www.delorie.com/djgpp/

        Source code to scan Windows LAN was originally written and
        placed in the Public Domain by Felix Kasza. Copied from Felix
        Kasza's Win32 Samples page at MVPS.ORG.
        https://www.mvps.org/

        Source code for colours in curses interface was copied from
        the PDCurses demo program 'tui'. The 'tui' demo program was
        originally written by P.J. Kunst and placed in the Public
        Domain.

        Markus Kuhn's free wcwidth() and wcwidth_cjk() implementation is used.
        See also https://www.cl.cam.ac.uk/~mgk25/unicode.html

        Rugxulo is the original autor of query_con_codepage(),
        which is in the public domain.

3.0 Acknowledgements

        Thanks to the following people for giving ideas and/or
        reporting/solving bugs:

        Leo Sevat           (First user)
        Paul Lippens        (? I forgot. ew)
        Ondrej Popp         (relative treefiles)
        Ad Vaassen          (subdirectories)
        Michael Magan       (interface)
        Christopher Drexler (bugfix on SGI IRIX64)
        Richard Tietjen     (HOME on DOS/Windows)
        Howard Schwartz     (interface: use letters, WCDHOME)
        Ajit J. Thakkar     (zsh on windows)
        Christian Mondrup   (man page)
        Gary R. Johnson     (graphical tree mode)
        Peter Gutmann       (just go mode)
        Etienne Joarlette   (SunOS makefile)
        Edwin Rijpkema      (zoom in graphical tree mode)
        Juhapekka Tolvanen  (man page)
        Andre vd Avoird     (Keep paths, -k)
        Kevin M. Rosenberg  (patch for compile problems w.r.t. gcc and
                            <stdbool.h>, man page)
        Zoltan Varady       (fix compile problems on Mac OS X/Darwin)
        Eric Auer           (default makefile for DOS 16 bit (compact
                            memory model) works again)
        Val Vakar           (WCDFILTER)
        Jari Aalto          (man page improvements)
        Jari Aalto          (option -l takes alias directly)
        Jari Aalto          (in match list key z does page down.)
        Jari Aalto          (Swap options -v and -V.)
        Jari Aalto          (Unix: Replace volume manager path of HOME dir by "$HOME")
        Jari Aalto          (Makefile improvements)
        Jari Aalto          (Updated installation documentation)
        Jari Aalto          (Code cleanup)
        Jari Aalto          (Generate manual from Perl POD file)
        Jari Aalto          (Reformat README file.)
        Jari Aalto          (Fix compilation on Solaris)
        Jari Aalto          (Version date in ISO 8601 format)
        Gabor Grothendieck  (UNC paths support)
        Gabor Grothendieck  (automatically set PDC_RESTORE_SCREEN)
        Gabor Grothendieck  (original console colours on windows)
        Mark Hessling       (original console colours on windows)
        Mark Hessling       (fix: scroll away problem on Windows NT/2000/XP)
        Ken Zinnato         (alternative tree navigation)
        Scott D Friedemann  (fix: curses interface writes uninitialised data to screen)
        Richard Boss        (dump matches to stdout)
        Richard Boss        (8-bit characters)
        Richard Boss        (print match list at bottom of console)
        Roland Messier      Shell script to compile wcd for QNX 4.25 systems.
        Elbert Pol          Port to OS/2 Warp
        Billy Chen          Optional colours in graphical mode (option -K)
        Billy Chen          Less screen movement when navigating in graphical mode.
        anonymous           Alternate stack file support.
        Laurence Errington  Simpler installation instructions for Windows Command Prompt
        anonymous           Support user names with spaces on Windows.
        Justin Lecher       Makefile improvements.
        Eli Zaretskii       Don't follow symbolic links on Windows.
        Thomas Dickey       Use of ncurses on Windows.
        Misty De Meo        Fix: Compilation on OS X/FreeBSD.
        David Binderman     Fixed a dangerous string usage.
        Benno Schulenberg   Cleanup user interface messages.
        Andreas Schwab      Fix: etc/profile.d/wcd.sh: wcd function was overwriting shell's $go variable.
        Erik Rijshouwer     Idea for option -ls, list the aliases.
        Martin              Report bug that wcd DRIVE:DIR was broken in 6.0.0.


    3.1 Translators

        Thanks to the following translators:

        Since verion 5.2.5 wcd is part of the Translation Project (TP).
        All translations of the messages go via the Translation Project.
        see https://translationproject.org/domain/wcd.html

        Brazilian Portuguese  Rafael Fontenelle            Version 6.0.1
        Chinese (simplified)  Mingcong Bai (Jeff) and      Version 5.3.1
                              Mingye Wang (Arthur)
        Danish                Joe Hansen                   Version 6.0.0
        Dutch                 Erwin Waterlander            Version 4.0.0 - 5.2.4
        Dutch                 Benno Schulenberg            Version 5.2.5 - 5.3.3
        Esperanto             Benno Schulenberg            Version 5.2.5 - 5.3.3
        Esperanto             Felipe Castro                Version 6.0.4
        Finnish               Jari Aalto                   Version 5.1.0 - 5.2.4
        Finnish               Jorma Karvonen               Version 5.2.5 - 5.3.3
        French                Grégoire Scano               Version 6.0.3 - 6.0.4
        Friulian              Fabio Tomat                  Version 6.0.2
        German                Philipp Thomas               Version 5.1.3 - 5.2.3,
                                                           5.3.3 - 5.3.4
        German                Lars Wendler                 Version 5.2.4
        German                Mario Blättermann            Version 5.2.5 - 5.2.6
        Romanian              Remus-Gabriel Chelu          Version 6.0.5
        Serbian               Мирослав Николић             Version 5.3.4
        Spanish               Julio A. Freyre-Gonzalez     Version 5.0.4 - 5.2.4
        Spanish               Francisco Javier Serrador    Version 6.0.2
        Swedish               Josef Andersson              Version 6.0.5
        Ukrainian             Yuri Chornoivan              Version 5.2.5 - 6.0.0
        Vietnamese            Trần Ngọc Quân               Version 5.2.5 - 6.0.0


        Translations of the manual:
        See https://translationproject.org/domain/wcd-man.html

        Brazilian Portuguese  Rafael Fontenelle            Version 6.0.1 - 6.0.3
        Dutch                 Erwin Waterlander            Version 5.2.5 - 6.0.3
        German                Mario Blättermann            Version 5.2.5 - 6.0.3
        French                Grégoire Scano               Version 6.0.3 - 6.0.4
        Romanian              Remus-Gabriel Chelu          Version 6.0.5
        Serbian               Мирослав Николић             Version 6.0.4
        Swedish               Josef Andersson              Version 6.0.5
        Ukrainian             Yuri Chornoivan              Version 5.2.5 - 6.0.3


    3.2 Works of others used in the program

        Thanks to the following people for using their Free software:

        Ondrej Popp,                      C3PO
        Jason Mathews,                    dosdir (until version 5.3.4)
        Mark Adler,                       recmatch()
        DJ Delorie                        _fixpath()
        Borja Etxebarria & Olivier Sirol  Ninux Czo Directory
        Felix Kasza                       WIN32 API sample WNetOpenEnum()/WNetEnumResource()
                                          MVPS.ORG https://www.mvps.org/
        Markus Kuhn                       wcwidth() and wcwidth_cjk()
                                          https://www.cl.cam.ac.uk/~mgk25/unicode.html
        Rugxulo                           query_con_codepage()
                                          https://sites.google.com/site/rugxulo/

4.0 Contact and Download information


        I can be contacted via E-mail: waterlan@xs4all.nl

        --

        Latest development source code is maintained in
        SourceForge Git repository:

        git clone git://git.code.sf.net/p/wcd/wcd


        The latest WCD packages, executables and sources, can be downloaded from
        this internet-page:

        https://waterlan.home.xs4all.nl/

        --

        SourceForge project page:
        https://sourceforge.net/projects/wcd/

        --

        For each release of wcd there are two source packages
        (the question marks indicate the version number):

        wcd-?.?.?.tar.gz   : source package
           Source code in unix text.

        wcd???.zip : source package
           Source code in DOS text.


        --

        Wcd is also distributed by:

        Debian Linux
        https://packages.debian.org/search?keywords=wcd

        Ubuntu Linux
        https://packages.ubuntu.com/

        Fedora Linux

        openSuse Linux

        Gentoo Linux

        Simtel.Net:
        Search: wcd
        SYSTEM UTILITIES > File management and conversion utils > wcd

        Ibiblio (was Metalab (was SunSite)):
        https://www.ibiblio.org/pub/Linux/utils/shell/


-- Erwin Waterlander
