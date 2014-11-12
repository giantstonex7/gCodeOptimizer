'''
Created on Nov 12, 2014

@author: adamsb
'''



import sqlite3, math, time, sys
import re
from lib2to3.pgen2.grammar import opmap
class Optimizer:
    dbConn = None
    dbCursor = None
    
    outputGCode = []
    startTime = None
    originalTraversal = 0
    optimizedTraversal = 0
    
    def progressBar(self, done, total, text=""):
    
        
        if done > total: 
            return
    
        if self.startTime is None:
            self.startTime = time.time()
        now = time.time()
    
        percent_done = float(done) / float(total)
    
        bar = int(math.floor(percent_done * 30))

        status_bar="\r" + text+ "[" + ("=" * bar)
       
        if bar < 30:
            status_bar += ">"
            status_bar +=(" " * (30-bar));
        else:
            status_bar += "="

        disp = "{:3.0f}".format(percent_done*100)

        status_bar += "] "+ disp +"%  "+str(done)+"/"+str(total)

        rate = (now-self.startTime)/done;
        left = total - done;
        eta = round(rate * left, 2)
        
        elapsed = now - self.startTime;

        status_bar += " remaining: " + str(int(eta)) + " sec.  elapsed: " + str(int(elapsed)) + " sec."

        sys.stdout.write(status_bar)
        sys.stdout.flush()
        

        if (done == total):
            print
            self.start_time = None
        
    def getNumberAfterChar(self, line, character):
        matches = re.search(character+'([-+]?[0-9]*\.?[0-9]+)', line);
        if matches:
            if len(matches.groups()) > 1:
                print "\nERROR: Multiple parameters with same name on a line.\n"
                exit -1
            return matches.group(1)
        else:
            return False
    
    def getLength(self, start, end):
        return math.sqrt(math.pow(start[0] - end[0], 2) + math.pow(start[1] - end[1], 2));    
    
    def getPosition(self, line):
        x = self.getNumberAfterChar(line, 'X')
        y = self.getNumberAfterChar(line, 'Y')
        
        if (x is False or y is False):
            return None
        return (float(x), float(y))
        
    def isCoincident(self, point1, point2):
        return (point1[0] == point2[0]) and (point1[1] == point2[1])
    
    def getLinesCount(self):
        self.dbCursor.execute("SELECT COUNT(*) from lines")
        result = self.dbCursor.fetchone();
        return result[0]
    
    def getNearest(self, location):
        self.dbCursor.execute('''
            SELECT num, start_x, start_y, end_x, end_y,
             length, power, feedrate, 
             (start_x - :x )*(start_x - :x) + (start_y - :y)*(start_y - :y) as distance_start,
             (end_x - :x)*(end_x - :x) + (end_y - :y)*(end_y - :y) as distance_end
             FROM lines ORDER BY min(distance_start, distance_end), length LIMIT 1''', {"x": location[0], "y": location[1]})
        line = self.dbCursor.fetchone()
        if line is not None:
            self.dbCursor.execute('DELETE from lines where num = ?', (line['num'],))
        return line
        
    def moveTo(self, location, feedRate, code="G1"):
        self.outputf.write(code + " X" + str(location[0]) + " Y" + str(location[1]) + " F" + str(feedRate) + "\n")
        
    def laserOn(self, power):
        self.outputf.write("M3 S"+str(power)+"\n")
    
    def laserOff(self):
        self.outputf.write("M5\n")
        
    def __init__(self, inFileName, outFileName, traversalRate):
        self.dbConn = sqlite3.connect(':memory:')
        self.dbConn.row_factory = sqlite3.Row
        self.dbCursor = self.dbConn.cursor()
        self.traversalRate = traversalRate
        self.dbCursor.execute('''CREATE TABLE lines
            (num INT, start_x DOUBLE, start_y DOUBLE, end_x DOUBLE, end_y DOUBLE,
             length DOUBLE, power DOUBLE, feedrate DOUBLE);''')
        
        inputf = open (inFileName, 'r')
        self.outputf = open(outFileName, 'w')
        with inputf:
            totalInputLines = sum(1 for _ in inputf)
        inputf = open (inFileName, 'r')
        
        active = False
        lastPosition = (0, 0)
        power = 0
        headerOpen = True
        lineNum = 0
        feedRate = 100
        self.lastUsefulLine = 0
        for line in iter(inputf.readline, ''):
            line = line.rstrip()
            lineNum+=1
            self.progressBar(lineNum, totalInputLines, "Loading GCode...\t\t")
            if len(line) == 0:
                continue
            elif line[0] == 'G':
                codeNum = int(self.getNumberAfterChar(line, '^G'));
                
                if (codeNum == 0) or (codeNum == 1):
                    headerOpen = False
                    newPosition = self.getPosition(line)
                    if newPosition is None:
                        continue
                    newFeedRate = float(self.getNumberAfterChar(line, 'F'))
                    if newFeedRate:
                        feedRate = newFeedRate
                    length = self.getLength(lastPosition, newPosition)
                    values = (lineNum,
                         lastPosition[0], lastPosition[1],
                         newPosition[0], newPosition[1],
                         length, power, feedRate
                        ) 
                    if active:
                        self.dbCursor.execute('''INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', values)
                    else:
                        self.originalTraversal+=length
                        
                    self.lastUsefulLine = inputf.tell()
                    
                    lastPosition = newPosition
                elif headerOpen:
                    self.outputf.write(line + "\n"); 
            elif line[0] == 'M':
                
                codeNum = int(self.getNumberAfterChar(line, '^M'));
                    
                if (codeNum == 3):
                    headerOpen = False
                    newPower = float(self.getNumberAfterChar(line, 'S'))
                    if newPower is not False:
                        power = newPower
                    active = True
                    self.lastUsefulLine = inputf.tell()    
                elif codeNum == 5:
                    headerOpen = False
                    active = False
                    self.lastUsefulLine = inputf.tell()    
                elif headerOpen:
                    self.outputf.write(line + "\n");
            elif headerOpen:
                self.outputf.write(line + "\n");   
       
        inputf.close()
        
        lastPosition = (0, 0)
        active = False
        power = 0
        processedLines = 0
        totalLines = self.getLinesCount()
        line = self.getNearest(lastPosition)
        
        while line is not None:
            processedLines += 1
            self.progressBar(processedLines, totalLines, "Optimizing GCode...\t\t")
            start = (line['start_x'], line['start_y'])
            end = (line['end_x'], line['end_y'])
            if line['distance_start'] < line['distance_end']:
                
                if not self.isCoincident(lastPosition, start):
                    self.laserOff();
                    active = False
                    self.optimizedTraversal += self.getLength(lastPosition, start)
                    self.moveTo(start, self.traversalRate, "G0");
                if (active is False) or power != line['power']:
                    power = line['power']
                    self.laserOn(power)
                    active = True
                self.moveTo(end, line['feedRate'])
                lastPosition = end
            else:
                if not self.isCoincident(lastPosition, end):
                    self.optimizedTraversal += self.getLength(lastPosition, end)
                    self.laserOff();
                    active = False
                    self.moveTo(end, self.traversalRate, "G0");
                if (active is False) or power != line['power']:
                    power = line['power']
                    active = True
                    self.laserOn(power)
                self.moveTo(start, line['feedRate'])
                lastPosition = start    
            
            line = self.getNearest(lastPosition)
         
         
        #Write the Footer
        inputf = open(inFileName, "r")
        inputf.seek(self.lastUsefulLine)
        for line in iter(inputf.readline, ''):
            self.outputf.write(line)
            
        self.outputf.close()   
            

import argparse

parser = argparse.ArgumentParser()

parser.add_argument("inputfile", help="Input GCode file to optimize")
parser.add_argument('outputfile', help="File to write optimized code")
parser.add_argument('-t', '--traversal', help="Traversal rate (defaults to 1000)", type=float, default=1000)
args = parser.parse_args()

optmzr = Optimizer(args.inputfile, args.outputfile, args.traversal)
print

print "Original Traversal: " + str(round(optmzr.originalTraversal, 2)) + " ",
print "Optimized Traversal: " + str(round(optmzr.optimizedTraversal, 2)) + " ",
print "(" + str(round((optmzr.optimizedTraversal/optmzr.originalTraversal)*100, 2))+ "%)"


