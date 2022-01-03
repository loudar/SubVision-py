# ArcGIS Skript
#
# Zweck:
# Anpassen von Haltungs- und Hausanschlussdaten mithilfe von Schachtsohlen
#
# Anmerkungen:
# Kommentare sind in Englisch verfasst, nur die ausgegebenen Nachrichten sind auf Deutsch.
# Damit wird möglichst viel Arbeit vermieden, falls das Skript mal bei Bedarf auf Englisch ausgeführt werden sollte.
# Der Ausgabeordner wird vor dem Ausführen nicht geleert, aus Übersichtsgründen sollte dieser also vorher leer sein.
#
# Für aktuelle Verwendung zu nutzende Parameter in ArcGis:
# Haltungen:        haltungen_neustadt.shp      Ursprungsdaten.
# Anschlüsse:       anschlussleitung.shp               Ursprungsdaten.
# Schächte:         schacht_adjust_3d_z.shp     Das manuell angepasste Feature der Schachtsohlen.
# Ausgabeordner:    <user-defined>              Sollte ein leerer Ordner sein. (Erzeugt viele Dateien)
#
# © Hochschule Bremen, 2021-2022
# Autor: Alexander Fritsch

import os
import math
import time

import arcpy
from arcpy import env

def logFeatureClasses(mode):
    """**Logs all feature classes in the output folder** to log.txt within the output folder.

    :param string mode: The file mode to use. Values: "w", "a"
    """
    if mode != "w" and mode != "a":
        raise ValueError('Use "w" (write) or "a" (append) as mode.')

    # Create feature classes array
    featureClasses = arcpy.ListFeatureClasses()

    # Open log file
    with open('log.txt', mode) as file:

        # Iterate through feature classes
        for featureClass in featureClasses:

            path = os.path.join(arcpy.env.workspace, featureClass)
            file.write("Feature class:     {0}\n".format(path))

            # Create fields array
            fields = arcpy.ListFields(featureClass)
            for field in fields:
                file.write("    Field:       {0}\n".format(field.name))
                file.write("    Type:        {0}\n".format(field.type))
                file.write("    Alias:       {0}\n".format(field.aliasName))
            #arcpy.CalculateField_management(haltung_intermediate, "haltung_XY", "[haltung_X]+[haltung_Y]")

        file.write("\n")
    # -------------------------------------------------------------------------------------#

def updateProgress(label, position=None):
    """**Updates the arcpy progress bar**

    :param string label: What to write into the label box.
    :param int position: [optional] The percentage for the progress bar.
    :returns: void
    """
    if label:
        arcpy.SetProgressorLabel(label)
    else:
        raise ValueError("Please specify a label when updating progress bar.")

    if position:
        arcpy.SetProgressorPosition(position)
    else:
        arcpy.SetProgressorPosition()
    # -------------------------------------------------------------------------------------#

def copyFeature(input, output):
    """Copies a feature class to another destination.

    :param string input: The feature class to copy.
    :param string output: The destination path to copy to. If .shp is not the end of the string, it will be appended.
    """

    if output[-4:] != ".shp":
        output += ".shp"

    updateProgress("Kopiere Feature {0}...".format(input))
    arcpy.CopyFeatures_management(input, output)

def convertFeatureToPoints(featureClass):
    """**Converts a feature class to Points, creates Geometry attribute fields and adds an ID based on X/Y-coordinates.**
    *Does not overwrite the input.*

    :param string featureClass: The feature class to convert.
    :returns: void
    """

    if featureClass[-4:] != ".shp":
        featureClass += ".shp"

    featureName = featureClass[:-4]
    feature = featureClass
    # Convert lines to points
    oldType = arcpy.Describe(feature).shapeType
    updateProgress("Konvertiere Vertices zu Punkten in {0}...".format(feature))
    createPath = output_path + "\\" + featureName + "_toPoints" # Use featureName to write new feature
    arcpy.FeatureVerticesToPoints_management(feature, createPath, "ALL")
    # arcpy.AddMessage("{0} erfolgreich von {1} zu Point konvertiert.".format(feature, oldType))

    # Calculate Geometry Attributes
    feature = featureName + "_toPoints.shp" # From now on, work with converted feature
    featureName = featureName + "_toPoints"

    # Add coordinate fields (ArcGIS 10.7 and up)
    updateProgress("Berechne Punkt-Koordinaten in {0}...".format(feature))
    arcpy.AddGeometryAttributes_management(feature, "POINT_X_Y_Z_M")
    arcpy.DeleteField_management(feature, "POINT_M")  # Delete, is never used

    # Following method for 10.6 and below
    # arcpy.AddField_management(featureClass, field_prefix + "_X", "DOUBLE")
    # arcpy.AddField_management(featureClass, field_prefix + "_Y", "DOUBLE")
    # arcpy.CalculateGeometryAttributes_management(featureClass, [["_X"], ["POINT_X"]])
    # arcpy.CalculateGeometryAttributes_management(featureClass, [["_Y"], ["POINT_Y"]])

    # Calculate XY-ID
    field_prefix = featureClass[0:1]
    arcpy.AddField_management(feature, field_prefix + "_XY", "DOUBLE")
    arcpy.CalculateField_management(feature, field_prefix + "_XY", "[POINT_X] + [POINT_Y]")
    updateProgress("{0} erfolgreich berechnet.".format(feature))
    #-------------------------------------------------------------------------------------#

def interpolateFeatureZ(featureClass, matchFieldID, referenceClass, refFieldX, refFieldY, refFieldID):
    """Interpolates the Z value of a point feature based on a reference feature. Usage: Adjust a point on a line between to other points.

    :param string featureClass: The feature class to adjust.
    :param string matchFieldID: The name of the field in featureClass to match against refFieldID in referenceClass
    :param string referenceClass: The feature class to reference for start and end point.
    :param string refFieldX: The name of the field the reference X values are stored in.
    :param string refFieldY: The name of the field the reference Y values are stored in.
    :param string refFieldID: The name of the field to be matched against with matchFieldID.
    :returns: void
    """

    if featureClass[-4:] != ".shp":
        featureClass += ".shp"

    # Util variables
    saved_fid = None
    cIndex = 0
    adjustedPoints = 0
    field_prefix = featureClass[0:1]

    # Using the new data-access search cursor, because getValue() doesn't work for the old one, somehow
    fields = [f.name for f in arcpy.ListFields(featureClass)]
    refFields = [f.name for f in arcpy.ListFields(referenceClass)]

    # Find indexes for field names
    # Source feature ↓
    xIndex = fields.index("POINT_X")
    yIndex = fields.index("POINT_Y")
    zIndex = fields.index("POINT_Z")
    xyIndex = fields.index(field_prefix + "_XY")
    fidIndex = fields.index("FID")
    matchFieldIndex = fields.index(matchFieldID)
    # Reference feature ↓
    refIndexX = refFields.index(refFieldX)
    refIndexY = refFields.index(refFieldY)
    refIndexZ = refFields.index("Z")
    refIndexXY = refFields.index("schacht_XY")

    # Build delimited field names (can cause SQL issues if not done)
    matchFieldIDdelimited = arcpy.AddFieldDelimiters(featureClass, matchFieldID)
    FIDdelimited = arcpy.AddFieldDelimiters(featureClass, "FID")
    refFieldIDdelimited = arcpy.AddFieldDelimiters(referenceClass, refFieldID)

    # Fetch cursor into array to minize cursor usage
    rows = [row for row in arcpy.da.UpdateCursor(featureClass, "*", sql_clause=(
        None, "ORDER BY {0}, {1}".format(matchFieldIDdelimited, FIDdelimited)))]
    refRows = [row for row in arcpy.da.SearchCursor(referenceClass, "*")]
    rowCount = len(rows)

    for row in rows:
        if saved_fid == row[matchFieldIndex]:
            continueLine = True
        else:
            continueLine = False
            # Reset found references if line isn't continued
            startPoint = None
            endPoint = None
            startRef = None
            endRef = None
            saved_fid = row[matchFieldIndex]
        updateProgress("Verarbeite Punkt {0}/{1}... (Datenabfrage)".format(cIndex, rowCount))

        if not continueLine:
            # Get start+end points for line the current point was originally on
            for e in range(cIndex, rowCount):
                row2 = rows[e]
                if saved_fid == row2[matchFieldIndex] and not startPoint:
                    startPoint = row2
                if saved_fid == row2[matchFieldIndex] and startPoint:
                    endPoint = row2
                if startPoint and endPoint and saved_fid != row2[matchFieldIndex]:
                    break;

        if not startPoint or not endPoint:
            if showWarnings:
                arcpy.AddMessage("Warnung: Start- oder Endpunkt in Haltung von Punkt {0} nicht gefunden.".format(cIndex))
            row[zIndex] = 0
            cIndex += 1
            continue

        if not continueLine:
            # Find reference points based on start and end point
            for refRow in refRows:
                if refRow[refIndexXY] == startPoint[xyIndex]:
                    startRef = refRow
                if refRow[refIndexXY] == endPoint[xyIndex]:
                    endRef = refRow
                if startRef and endRef:
                    break

        if not startRef or not endRef:
            if showWarnings:
                arcpy.AddMessage("Warnung: Start- oder Endpunkt in Referenz von Punkt {0} nicht gefunden.".format(cIndex))
            row[zIndex] = 0
            cIndex += 1
            continue

        updateProgress("Verarbeite Punkt {0}/{1}... (Berechnung)".format(cIndex, rowCount))

        # Calculate base values
        xLength = startRef[refIndexX] - endRef[refIndexX]
        yLength = startRef[refIndexY] - endRef[refIndexY]
        baseLength = (xLength ** 2) + (yLength ** 2)

        # Calculate distance from start and end point
        xLength = row[xIndex] - startRef[refIndexX]
        yLength = row[yIndex] - startRef[refIndexY]
        toStartLength = (xLength ** 2) + (yLength ** 2)

        # Calculate Z-values
        startZ = startRef[refIndexZ]
        endZ = endRef[refIndexZ]
        zDif = startZ - endZ  # Can be negative and should be able to
        newZ = startZ - (math.sqrt((toStartLength / baseLength)) * zDif)  # Calculate new Z coord based on distance to start point
        row[zIndex] = newZ - row[zIndex]
        adjustedPoints += 1

        cIndex += 1

    updateProgress("Schreibe interpolierte Punkte in Feature...")
    rIndex = 0
    with arcpy.da.UpdateCursor(featureClass, fields, sql_clause=(None, "ORDER BY {0}, {1}".format(matchFieldIDdelimited, FIDdelimited))) as cursor:
        for row in cursor:
            row[zIndex] = rows[rIndex][zIndex]
            cursor.updateRow(row)
            rIndex += 1

    updateProgress("Passe Geometrie auf Tabellenwerte an...")
    arcpy.Adjust3DZ_management(featureClass, "NO_REVERSE", "POINT_Z")
    updateProgress("Alle Punkte in {0} erfolgreich interpoliert!".format(featureClass))

    # -------------------------------------------------------------------------------------#

def adjust3DZbyReference(featureA, matchA, groupA, featureB, matchB):
    """Takes Z values from featureB and transfers them to featureA where matchA = matchB.
    Assumes the input feature contains 3D points.
    Group parameter is currently ignored.

    :param string featureA: The feature class to adjust.
    :param string matchA: The name of the field in featureClass to match against matchB in featureB.
    :param string groupA: The field to group featureA by.
    :param string featureB: The feature class to reference.
    :param string matchB: The name of the field to be matched against with matchA.
    :returns: void
    """
    if featureA[-4:] != ".shp":
        featureA += ".shp"
    if featureB[-4:] != ".shp":
        featureB += ".shp"

    updateProgress("Passe 3D-Positionen von {0} an...".format(featureA))

    # Fetch all fields of features to reference later
    Afields = [f.name for f in arcpy.ListFields(featureA)]
    Bfields = [f.name for f in arcpy.ListFields(featureB)]

    # Find indexes for field names
    AmatchIndex = Afields.index(matchA)
    BmatchIndex = Bfields.index(matchB)
    AzIndex = Afields.index("POINT_Z")
    BzIndex = Bfields.index("POINT_Z")
    AgroupIndex = Afields.index(groupA)

    # Fetch cursor into array to minize cursor usage
    Arows = [row for row in arcpy.da.UpdateCursor(featureA, "*", sql_clause=(
        None, "ORDER BY {0}".format(groupA)))]
    Brows = [row for row in arcpy.da.SearchCursor(featureB, "*")]
    ArowCount = len(Arows)

    # Util variables
    cIndex = 0
    adjustedPoints = 0

    updateProgress("Suche nach übereinstimmenden IDs von {0}...".format(featureA))
    for Arow in Arows:
        updateProgress("Verarbeite Punkt {0}/{1}...".format(cIndex, ArowCount))
        idFound = False
        searchID = Arow[AmatchIndex]

        # Search for matching reference points
        for Brow in Brows:
            if searchID == Brow[BmatchIndex]:
                # Copy the adjustment (NOT the absolute) Z value
                Arow[AzIndex] = Brow[BzIndex]
                adjustedPoints += 1
                idFound = True
            if idFound:
                break

        if not idFound:
            Arow[AzIndex] = 0

        cIndex += 1

    updateProgress("Schreibe {0} angepasste Punkte in Feature {1}...".format(adjustedPoints, featureA))
    rIndex = 0
    with arcpy.da.UpdateCursor(featureA, Afields) as Aupdate:
        for AupRow in Aupdate:
            AupRow[AzIndex] = Arows[rIndex][AzIndex]
            Aupdate.updateRow(AupRow)
            rIndex += 1

    updateProgress("Passe Geometrie von {0} auf Tabellenwerte an...".format(featureA))
    arcpy.Adjust3DZ_management(featureA, "NO_REVERSE", "POINT_Z")
    updateProgress("{0} Punkte in {1} erfolgreich angepasst!".format(adjustedPoints, featureA))

    # -------------------------------------------------------------------------------------#

class Timer:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.startTime = time.time()

    def __exit__(self, a, b, c):
        self.endTime = time.time()
        self.difference = self.endTime - self.startTime
        arcpy.AddMessage("{0}: {1:.2f}s".format(self.name, self.difference))

with Timer("Setup") as timer:
    # Initate arcpy progressor
    arcpy.SetProgressor("step", "...", 0, 7)
    updateProgress("Starte Prozess...")

    # Get parameters
    haltung_path = arcpy.GetParameterAsText(0)
    anschluss_path = arcpy.GetParameterAsText(1)
    schacht_path = arcpy.GetParameterAsText(2)
    output_path = arcpy.GetParameterAsText(3)
    showWarnings = arcpy.GetParameter(4)

    # Change workspace to output folder
    os.chdir(output_path)
    arcpy.env.workspace = output_path
    env.overwriteOutput = True

    # Copy features to output folder
    haltung_out = "haltungen_out.shp"
    anschluss_out = "anschluss_out.shp"
    schacht_out = "schacht_out.shp"
    copyFeature(haltung_path, haltung_out)
    copyFeature(anschluss_path, anschluss_out)
    copyFeature(schacht_path, schacht_out)
    # logFeatureClasses('w') # Can be used to check if features have been copied correctly

with Timer("Zu Punkte konvertieren") as timer:
    # Access feature class array and convert data to points
    featureClasses = arcpy.ListFeatureClasses()
    for featureClass in featureClasses:
        if featureClass == anschluss_out or featureClass == haltung_out:
            convertFeatureToPoints(featureClass)

# Update base line vertices Z values
with Timer("3D Daten anpassen (Teil 1)") as timer:
    interpolateFeatureZ("haltungen_out_toPoints", "ORIG_FID", schacht_out, "schacht_X", "schacht_Y", "schacht_XY")
with Timer("3D Daten anpassen (Teil 2)") as timer:
    adjust3DZbyReference("anschluss_out_toPoints", "a_XY", "ORIG_FID", "haltungen_out_toPoints", "h_XY")

with Timer("Zu Linien konvertieren") as timer:
    updateProgress("Wandle anschluss_out_toPoints in Linien um...")
    arcpy.PointsToLine_management("anschluss_out_toPoints.shp", "anschluss_out_lines.shp", "ORIG_FID", "ORIG_FID")
    updateProgress("Wandle haltungen_out_toPoints in Linien um...")
    arcpy.PointsToLine_management("haltungen_out_toPoints.shp", "haltungen_out_lines.shp", "ORIG_FID", "ORIG_FID")

arcpy.AddMessage("Skript erfolgreich beendet und alle Daten verarbeitet!")