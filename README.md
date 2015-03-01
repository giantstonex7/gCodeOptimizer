An (awful) attempt at optimizing GCode for laser cutting.  It uses a brute force
method for finding the next nearest point.  Since the problem is NP hard, the 
execution time will increase exponentially as the input file size increases.

In practice, this hasn't been a /huge/ problem (for large files, the processing
time is long, but the savings in cut time on the laser are worth the extra
processing time).

Requires pysqlite2
 
Note this code relies on M3/M5 being used to turn the laser on and off and sections
of code to be optimzed being tagged ("; Start of path" and "; End of Path" by 
default).  Each section is optimized separately so that path orders can be preserved.

python gCodeOptimizer.py --help


